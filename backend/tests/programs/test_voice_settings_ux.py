"""「AI 전화」 설정 손보기(11-24 PM 실제 사용): 모델은 목록에서 · 번호는 알림 연결에서 · 저장하면 카드(지우기 길) ·
걸기 전에 모델 확인 · 세션(AI 음성 모델)을 열지 못한 통화는 그 까닭을 말한다.

구글은 부르지 않는다 — `live_models.google_client` 를 가짜로 바꾼다. SDK 도 대본 가짜(Task 60 의 FakeSdk·World)다.
"""

import logging
from types import SimpleNamespace

import pytest

from app.notify import diagnostics_voice as dv
from app.notify import live_models
from app.outreach import phone, redact
from app.outreach.voice import numbers
from app.programs.notify_settings import diagnose as diagnose_mod
from app.store.tables_outreach import NotifyConnection, VoiceSettings
from tests.notify.test_diagnostics_voice import GOOD_CALL, FakeAgent, FakeSdk, World
from tests.notify.test_diagnostics_voice import run as run_checks
from tests.outreach_doubles import SENTINEL_KEY, SENTINEL_PHONE
from tests.programs.test_voice_settings_api import (
    AGENT,
    AGENT_DIGITS,
    BASE,
    GOOGLE_KEY,
    NEW_GOOGLE_KEY,
    Spy,
    assert_no_leak,
    call_body,
    connection,
    diag,
    put,
    ready,
    stored,
)
from tests.provider_doubles import KAT_ACCOUNT, KAT_SENDER

pytestmark = pytest.mark.usefixtures("time_guard")

LIVE = "bidiGenerateContent"
SENDER_MASKED = phone.mask(KAT_SENDER)


def model(name: str, *actions: str) -> SimpleNamespace:
    return SimpleNamespace(name=f"models/{name}", display_name=name.upper(), supported_actions=list(actions))


class FakePager:
    """첫 쪽(page)만 읽어야 한다 — 다음 쪽으로 넘겨 읽으면(iter) 시험이 실패한다."""

    def __init__(self, items: list) -> None:
        self.page = items

    def __iter__(self):
        raise AssertionError("모델 목록은 첫 쪽만 읽어야 합니다(요청 한 번)")


class FakeGoogle:
    """`live_models.google_client` 대역: 받은 키·시간 제한·요청을 적고, 정해 둔 목록이나 오류를 돌려준다."""

    def __init__(self, items: list | None = None, error: BaseException | None = None) -> None:
        self.items = items if items is not None else [model("gemini-3.8-live", "generateContent", LIVE),
                                                      model("gemini-3.8-flash", "generateContent")]
        self.error = error
        self.keys: list[str] = []
        self.timeouts: list[float] = []
        self.requests: list[object] = []
        self.registered: list[bool] = []

    def __call__(self, key: str, timeout_s: float):
        self.keys.append(key)
        self.timeouts.append(timeout_s)
        self.registered.append(key in redact.secrets())  # 쓰기 전에 로그 거르개에 올렸는가
        owner = self

        class Models:
            def list(self, *, config=None):
                owner.requests.append(config)
                if owner.error is not None:
                    raise owner.error
                return FakePager(owner.items)

        return SimpleNamespace(models=Models())


@pytest.fixture
def google(monkeypatch) -> FakeGoogle:
    fake = FakeGoogle()
    monkeypatch.setattr(live_models, "google_client", fake)
    return fake


@pytest.fixture
def spy(monkeypatch) -> Spy:
    found = Spy()
    monkeypatch.setattr(dv, "run_voice_checks", found)
    return found


def models(client, admin, cid: int):
    return client.get(f"{BASE}/{cid}/voice/models", headers=admin)


# ── 번호·모델 규칙(한 곳) ─────────────────────────────────────────────


def test_effective_agent_number_prefers_the_voice_number_then_the_connection_sender():
    conn = SimpleNamespace(sender_number=KAT_SENDER)
    assert numbers.effective_agent_number(conn, None) == KAT_SENDER
    assert numbers.effective_agent_number(conn, SimpleNamespace(agent_number=None)) == KAT_SENDER
    assert numbers.effective_agent_number(conn, SimpleNamespace(agent_number="")) == KAT_SENDER
    assert numbers.effective_agent_number(conn, SimpleNamespace(agent_number=AGENT_DIGITS)) == AGENT_DIGITS
    assert numbers.effective_agent_number(SimpleNamespace(sender_number=None), None) is None
    assert numbers.agent_number_source(conn, None) == "connection"
    assert numbers.agent_number_source(conn, SimpleNamespace(agent_number=AGENT_DIGITS)) == "voice"
    assert numbers.agent_number_source(SimpleNamespace(sender_number=None), SimpleNamespace(agent_number=None)) is None


def test_empty_google_model_means_the_current_live_model_never_the_sdk_default():
    assert numbers.DEFAULT_LIVE_MODEL == "gemini-3.8-live"
    assert numbers.effective_model("google", "") == numbers.DEFAULT_LIVE_MODEL
    assert numbers.effective_model("google", None) == numbers.DEFAULT_LIVE_MODEL
    assert numbers.effective_model("google", "gemini-x") == "gemini-x"
    assert numbers.effective_model("openai", "") is None  # 다른 공급자는 그대로(빈 값 = SDK 기본)
    assert numbers.effective_model("openai", "gpt-rt") == "gpt-rt"
    assert numbers.effective_model("dashboard", "") is None
    assert live_models.FALLBACK[0] == numbers.DEFAULT_LIVE_MODEL


# ── GET …/voice: 저장했는지 · 실제로 쓰는 번호와 그 출처 · 실제로 쓰는 모델 ─────────


def test_voice_reports_the_effective_number_with_its_source_and_the_effective_model(client, admin, fake_provider):
    conn = connection(client, admin, SENTINEL_PHONE)
    cid = conn["id"]
    body = client.get(f"{BASE}/{cid}/voice", headers=admin).json()
    assert body["saved"] is False and body["agent_number_masked"] is None
    assert (body["agent_number_effective_masked"], body["agent_number_source"]) == (SENDER_MASKED, "connection")
    assert body["model_effective"] == "gemini-3.8-live" and body["model"] == ""
    assert body["test_call_index"] == 0  # 연결의 번호로 걸 수 있다
    saved = put(client, admin, cid, secret=GOOGLE_KEY).json()
    assert saved["saved"] is True and saved["agent_number_source"] == "connection"
    own = put(client, admin, cid, agent_number=AGENT).json()
    assert (own["agent_number_masked"], own["agent_number_effective_masked"], own["agent_number_source"]) == (
        "070-****-0144", "070-****-0144", "voice")
    back = put(client, admin, cid, agent_number=None).json()
    assert (back["agent_number_effective_masked"], back["agent_number_source"]) == (SENDER_MASKED, "connection")
    other = put(client, admin, cid, provider="openai", secret=NEW_GOOGLE_KEY).json()
    assert other["model_effective"] == ""  # OpenAI 는 지금처럼(빈 값 = SDK 기본)
    for payload in (body, saved, own, back, other):
        assert_no_leak(payload)


def test_no_number_anywhere_means_no_call(client, admin, fake_provider, session, spy, google):
    conn = connection(client, admin, SENTINEL_PHONE)
    cid = conn["id"]
    session.get(NotifyConnection, cid).sender_number = None
    session.commit()
    assert put(client, admin, cid, secret=GOOGLE_KEY).status_code == 200
    body = client.get(f"{BASE}/{cid}/voice", headers=admin).json()
    assert body["agent_number_effective_masked"] is None and body["agent_number_source"] is None
    assert body["test_call_index"] is None
    r = diag(client, admin, cid, call_body(conn))
    assert r.status_code == 422 and r.json()["code"] == "no_agent_number" and spy.calls == []


# ── 진단은 실제로 쓰는 값으로 ────────────────────────────────────────


def test_diagnosis_uses_the_connection_number_and_the_default_model_when_left_empty(client, admin, fake_provider, spy,
                                                                                   google):
    conn = connection(client, admin, SENTINEL_PHONE)
    cid = conn["id"]
    assert put(client, admin, cid, secret=GOOGLE_KEY).status_code == 200  # 번호·모델은 비움
    r = diag(client, admin, cid, call_body(conn))
    assert r.status_code == 200, r.text
    seen = spy.calls[0]
    assert seen["agent_number"] == KAT_SENDER and seen["voice"].model == "gemini-3.8-live"
    assert google.keys == [GOOGLE_KEY] and len(google.requests) == 1  # 걸기 전에 목록을 한 번 봤다


# ── 모델 목록 길 ─────────────────────────────────────────────────────


def test_models_lists_only_live_models_for_the_stored_key_in_one_bounded_request(client, admin, fake_provider, google,
                                                                                 caplog):
    caplog.set_level(logging.DEBUG)
    google.items = [model("gemini-3.8-flash", "generateContent"), model("gemini-x-live", LIVE),
                    model("gemini-3.8-live", "generateContent", LIVE), model("bad name!", LIVE),
                    SimpleNamespace(name=None, supported_actions=[LIVE]), model("embed-1", "embedContent")]
    cid = ready(client, admin)["id"]
    r = models(client, admin, cid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"models": ["gemini-3.8-live", "gemini-x-live"], "default": "gemini-3.8-live", "fallback": False,
                    "reason": None}
    assert google.keys == [GOOGLE_KEY] and google.registered == [True]
    assert len(google.requests) == 1 and 0 < google.timeouts[0] <= 10
    assert GOOGLE_KEY not in r.text and KAT_ACCOUNT not in r.text
    assert all(GOOGLE_KEY not in rec.getMessage() for rec in caplog.records)


def test_models_list_is_capped(client, admin, fake_provider, google):
    google.items = [model(f"gemini-live-{n}", LIVE) for n in range(500)]
    cid = ready(client, admin)["id"]
    body = models(client, admin, cid).json()
    assert 0 < len(body["models"]) <= live_models.MAX_MODELS and body["fallback"] is False


class Rejected(Exception):
    """구글 오류의 꼴(`code` = HTTP 상태). 글에는 키가 든다."""

    def __init__(self, code: int) -> None:
        super().__init__(f"API key {GOOGLE_KEY} not valid · account {KAT_ACCOUNT}")
        self.code = code


@pytest.mark.parametrize(("error", "words"), [
    (Rejected(400), "키"), (Rejected(403), "키"), (TimeoutError(), "시간"),
    (RuntimeError(f"boom {GOOGLE_KEY}"), "읽지 못해"), (ImportError("google-genai"), "묶음"),
])
def test_models_fall_back_to_a_small_static_list_with_a_plain_reason(client, admin, fake_provider, google, caplog,
                                                                     error, words):
    caplog.set_level(logging.DEBUG)
    google.error = error
    cid = ready(client, admin)["id"]
    r = models(client, admin, cid)
    assert r.status_code == 200
    body = r.json()
    assert body["fallback"] is True and body["models"][0] == "gemini-3.8-live" and body["default"] == "gemini-3.8-live"
    assert words in body["reason"] and GOOGLE_KEY not in r.text and KAT_ACCOUNT not in r.text
    assert all(GOOGLE_KEY not in rec.getMessage() and KAT_ACCOUNT not in rec.getMessage() for rec in caplog.records)


def test_models_without_a_stored_google_key_fall_back_without_asking(client, admin, fake_provider, google):
    cid = connection(client, admin)["id"]
    body = models(client, admin, cid).json()
    assert body["fallback"] is True and "키" in body["reason"] and google.keys == []
    assert put(client, admin, cid, provider="openai", secret=NEW_GOOGLE_KEY).status_code == 200
    body = models(client, admin, cid).json()
    assert body["fallback"] is True and google.keys == []  # 구글 키가 아니면 묻지 않는다


def test_models_when_google_lists_no_live_model_is_a_fallback(client, admin, fake_provider, google):
    google.items = [model("gemini-3.8-flash", "generateContent")]
    cid = ready(client, admin)["id"]
    body = models(client, admin, cid).json()
    assert body["fallback"] is True and body["models"][0] == "gemini-3.8-live" and body["reason"]


def test_models_is_for_admins_only(client, admin, user, fake_provider, google):
    cid = connection(client, admin)["id"]
    assert client.get(f"{BASE}/{cid}/voice/models").status_code == 401
    assert client.get(f"{BASE}/{cid}/voice/models", headers=user).status_code == 403
    assert client.get(f"{BASE}/999/voice/models", headers=admin).status_code == 404


# ── 걸기 전에 모델 확인 ──────────────────────────────────────────────


@pytest.mark.parametrize("part", ["connection", "call"])
def test_a_model_the_key_cannot_use_fails_p5_and_places_no_call(client, admin, fake_provider, spy, google, session,
                                                                part):
    conn = ready(client, admin)
    cid = conn["id"]
    assert put(client, admin, cid, model="gemini-3.1-flash-live-preview").status_code == 200
    r = diag(client, admin, cid, call_body(conn) if part == "call" else {})
    assert r.status_code == 200, r.text
    rows = {s["id"]: s for s in r.json()["steps"]}
    assert rows["P5"]["ok"] is False and rows["P5"]["code"] == "model_not_available"
    assert rows["P5"]["detail"] == ("AI 음성 모델 〈gemini-3.1-flash-live-preview〉을 이 키로 쓸 수 없습니다 — "
                                    "모델을 다시 골라 주세요")
    assert rows["P11"]["skipped"] is True
    assert spy.calls == []  # SDK 를 건드리지 않았다 — 전화도 없다
    assert r.json()["calls"] == [] and r.json()["called_real"] is False
    assert client.get(f"{BASE}/{cid}/voice", headers=admin).json()["status"] == "failed"
    assert stored(session, cid)["state"] == "done" and cid not in diagnose_mod._RUNNING
    if part == "call":
        assert rows["P6"]["skipped"] is True and rows["P6"]["maybe_sent"] is False


def test_when_the_list_cannot_be_read_the_diagnosis_goes_ahead_as_before(client, admin, fake_provider, spy, google):
    google.error = TimeoutError()
    conn = ready(client, admin)
    r = diag(client, admin, conn["id"], call_body(conn))
    assert r.status_code == 200 and len(spy.calls) == 1


def test_other_providers_are_not_checked_against_the_google_list(client, admin, fake_provider, spy, google):
    conn = ready(client, admin)
    assert put(client, admin, conn["id"], provider="openai", secret=NEW_GOOGLE_KEY).status_code == 200
    assert diag(client, admin, conn["id"], {}).status_code == 200
    assert google.keys == [] and spy.calls[0]["voice"].model is None


# ── 지우기 ───────────────────────────────────────────────────────────


def test_delete_removes_the_voice_settings_and_drops_the_key(client, admin, fake_provider, session, spy, google):
    conn = ready(client, admin)
    cid = conn["id"]
    assert GOOGLE_KEY in redact.secrets()
    r = client.delete(f"{BASE}/{cid}/voice", headers=admin)
    assert r.status_code == 204 and r.content == b""
    session.expire_all()
    assert session.get(VoiceSettings, cid) is None and GOOGLE_KEY not in redact.secrets()
    body = client.get(f"{BASE}/{cid}/voice", headers=admin).json()
    assert body["saved"] is False and body["has_secret"] is False
    assert client.delete(f"{BASE}/{cid}/voice", headers=admin).status_code == 204  # 이미 없으면 그대로
    assert session.get(NotifyConnection, cid) is not None  # 알림 연결은 그대로


def test_delete_keeps_a_key_another_connection_still_uses(client, admin, fake_provider):
    first = ready(client, admin)["id"]
    second = connection(client, admin)["id"]
    assert put(client, admin, second, secret=GOOGLE_KEY).status_code == 200
    assert client.delete(f"{BASE}/{first}/voice", headers=admin).status_code == 204
    assert GOOGLE_KEY in redact.secrets()


def test_delete_is_refused_while_a_diagnosis_runs_and_for_non_admins(client, admin, user, fake_provider, session):
    cid = ready(client, admin)["id"]
    diagnose_mod._RUNNING.add(cid)
    try:
        r = client.delete(f"{BASE}/{cid}/voice", headers=admin)
        assert r.status_code == 409 and r.json()["code"] == "diagnosis_running"
    finally:
        diagnose_mod._RUNNING.discard(cid)
    assert session.get(VoiceSettings, cid) is not None
    assert client.delete(f"{BASE}/{cid}/voice").status_code == 401
    assert client.delete(f"{BASE}/{cid}/voice", headers=user).status_code == 403
    assert client.delete(f"{BASE}/999/voice", headers=admin).status_code == 404


# ── 세션을 열지 못한 통화(오늘 아침처럼) ─────────────────────────────


class Http404(Exception):
    """websockets 의 InvalidStatus 꼴: `response.status_code`. 글에는 키가 든다."""

    def __init__(self) -> None:
        super().__init__(f"server rejected WebSocket connection: HTTP 404 key={GOOGLE_KEY}")
        self.response = SimpleNamespace(status_code=404)


class SessionFails(FakeSdk):
    """통화는 시작되지만 SDK 가 AI 음성 모델 세션을 열지 못한다(실제 SDK 와 같은 로그 줄을 남긴다)."""

    def ClawOpsAgent(self, **kw):
        agent = SessionFailAgent(self, **kw)
        self.agents.append(agent)
        return agent


class SessionFailAgent(FakeAgent):
    async def step(self, call, kind, *args) -> None:
        if kind == "session_failed":
            try:
                raise RuntimeError("session start") from Http404()
            except RuntimeError as e:
                sdk_log = logging.getLogger("clawops.agent")
                sdk_log.error("Session start failed for %s: %s", call.call_id, e, exc_info=True)  # SDK 와 같은 꼴
            return
        await super().step(call, kind, *args)


NO_SESSION_CALL = ((1000, "call_start"), (1100, "session_failed"), (1500, "call_end"))


async def test_a_call_whose_model_session_cannot_start_says_so_on_p6():
    world = World()
    sdk = SessionFails(world, calls=[NO_SESSION_CALL])
    out = await run_checks(world, sdk, steps=(5, 6, 7, 8), call_to=SENTINEL_PHONE)
    assert out["P6"].ok is False and out["P6"].code == "model_connect_failed"
    assert out["P6"].detail.startswith("AI 음성 모델에 연결하지 못했습니다") and "404" in out["P6"].detail
    assert out["P6"].data == {"http_status": 404} and out["P6"].maybe_sent is False
    for n in ("P7", "P8"):
        assert out[n].skipped is True and out[n].code == "skipped_no_model"
    assert "받아쓰기가 오지 않았습니다" not in out["P7"].detail


async def test_a_good_call_is_not_touched_by_the_session_watch():
    world = World()
    out = await run_checks(world, FakeSdk(world, calls=[GOOD_CALL]), steps=(5, 6, 7, 8), call_to=SENTINEL_PHONE)
    assert [out[n].code for n in ("P6", "P7", "P8")] == ["ok", "ok", "ok"]


async def test_another_calls_session_failure_is_not_ours():
    world = World()

    class Stranger(FakeSdk):
        def ClawOpsAgent(self, **kw):
            agent = super().ClawOpsAgent(**kw)
            logging.getLogger("clawops.agent").error("Session start failed for %s: %s", "CA-OTHER", Http404(),
                                                     exc_info=(Http404, Http404(), None))
            return agent

    out = await run_checks(world, Stranger(world, calls=[GOOD_CALL]), steps=(5, 6), call_to=SENTINEL_PHONE)
    assert out["P6"].code == "ok"
    assert SENTINEL_KEY not in out["P6"].detail


def test_session_failure_is_read_from_raw_and_from_already_cleaned_log_lines():
    from app.notify.voice_sdk_logs import session_failure

    try:
        raise RuntimeError("session start") from Http404()
    except RuntimeError as e:
        error = e
    raw = logging.LogRecord("clawops.agent", logging.ERROR, __file__, 1, "Session start failed for %s: %s",
                            ("CA1", error), (RuntimeError, error, None))
    assert session_failure(raw) == ("CA1", 404)
    cleaned = logging.LogRecord("clawops.agent", logging.ERROR, __file__, 1,
                                "Session start failed for CA2: server rejected WebSocket connection: HTTP 404", (), None)
    assert session_failure(cleaned) == ("CA2", 404)
    vague = logging.LogRecord("clawops.agent", logging.ERROR, __file__, 1, "Session start failed for CA3: boom", (), None)
    assert session_failure(vague) == ("CA3", None)
    other = logging.LogRecord("clawops.agent", logging.INFO, __file__, 1, "Media stream started: %s", ("CA4",), None)
    assert session_failure(other) is None


# ── 고침 1: 결과 모름은 실패가 아님 · 모델 확인은 읽은 목록 전체로 · SDK 는 쓸 때만 ─────────


def _rows(**kinds: dict) -> list[dict]:
    from app.programs.notify_settings import voice as voice_mod

    out = [voice_mod._never(n) for n in dv.STEPS]
    for name, kw in kinds.items():
        n = int(name[1:])
        out[n - 5] = voice_mod._line(n, ran_at="2026-11-24T00:00:00+00:00", detail="글", **kw)
    return out


@pytest.mark.parametrize("code", ["cut_unconfirmed", "not_finished", "dial_timeout", "unknown"])
def test_a_call_of_unknown_outcome_is_never_a_failure(code):
    """서버의 실제 꼴: 결과를 모르는 통화 줄은 ok:false · skipped:false · maybe_sent:true · pending:false."""
    from app.programs.notify_settings import voice as voice_mod

    unknown = {"code": code, "maybe_sent": True}
    ok = {"code": "ok", "ok": True}
    assert voice_mod._status(_rows(P5=ok, P11=ok, P6=unknown)) == "ok"
    assert voice_mod._status(_rows(P5={"code": "timeout", "pending": True}, P6=unknown)) is None
    assert voice_mod._status(_rows(P6=unknown)) is None  # 모름만 있으면 앞 값 그대로
    assert voice_mod._status(_rows(P5=ok, P11={"code": "bad_number"}, P6=unknown)) == "failed"  # 분명한 실패는 그대로


def test_unknown_call_leaves_the_card_status_unfailed_end_to_end(client, admin, fake_provider, monkeypatch, google):
    conn = ready(client, admin)
    cid = conn["id"]
    monkeypatch.setattr(dv, "run_voice_checks", Spy({6: dv.VoiceStep(
        id="P6", label=dv.LABELS["P6"], ok=False, detail="끊겼는지 확인하지 못했습니다.", code="cut_unconfirmed",
        maybe_sent=True)}))
    body = diag(client, admin, cid, call_body(conn)).json()
    assert body["call_unknown"] is True
    p6 = next(s for s in body["steps"] if s["id"] == "P6")
    assert (p6["ok"], p6["skipped"], p6["maybe_sent"], p6["pending"]) == (False, False, True, False)
    assert client.get(f"{BASE}/{cid}/voice", headers=admin).json()["status"] == "ok"


def test_the_model_check_uses_every_live_model_read_not_the_shortened_display_list(client, admin, fake_provider,
                                                                                   spy, google):
    google.items = [model(f"gemini-live-{n}", LIVE) for n in range(100)]
    conn = ready(client, admin)
    cid = conn["id"]
    assert put(client, admin, cid, model="gemini-live-80").status_code == 200
    assert "gemini-live-80" not in models(client, admin, cid).json()["models"]  # 화면 목록은 짧게
    r = diag(client, admin, cid, call_body(conn))
    assert r.status_code == 200 and len(spy.calls) == 1  # 막지 않았다


def test_the_google_listing_lives_outside_the_voice_package():
    """outreach/voice 는 SDK 를 어디서도 import 하지 않는다(test_simulated 의 검사) — 구글 목록은 진단 쪽(app.notify)에 둔다."""
    from pathlib import Path

    voice_dir = Path(numbers.__file__).parent
    assert not (voice_dir / "live_models.py").exists()
    assert live_models.__name__ == "app.notify.live_models"
