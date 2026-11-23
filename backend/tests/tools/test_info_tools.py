"""info.list·info.call: 관리자가 연결한 범용 정보 API 를 에이전트가 고르고 부른다. 근거 보관·요청당 4번·키 지우기.

네트워크를 쓰지 않는다(app.info.generic 의 TRANSPORT·RESOLVE 를 가짜로, LLM 은 대본 가짜). 값은 모두 가상이다.
"""

import dataclasses
import json
import logging
import sqlite3
from contextlib import closing

import httpx
import pytest
from sqlalchemy import select

from app.agent.context import CUT_NOTE, UiContext, result_text
from app.agent.loop import run_turn
from app.config import Settings
from app.info import generic, kma, templates
from app.llm.client import LlmClient
from app.security.crypto import encrypt
from app.store import chats
from app.store.evidence import searches_since
from app.store.tables import (
    ChatMessage,
    EvidenceItem,
    EvidenceSearch,
    InfoConnection,
    TraceEvent,
    User,
    WorkflowStep,
)
from app.tools.registry import call, list_tools
from tests import info_doubles
from tests.info_doubles import BASE, HOST, KEY, KEY_ENCODED, ApiMock
from tests.kma_doubles import gateway_body
from tests.llm_doubles import add_connection
from tests.loop_doubles import ScriptedLlm, calls, reply

LIMIT_MESSAGE = "이번 요청에서 정보 API 조회를 4번 했습니다. 받은 값이나 분야 기본값을 쓰세요."
SECRETS = (KEY, KEY_ENCODED, KEY_ENCODED.lower(), "zyxwVUTSrqpo")
ARGS = {"connection_id": 0, "path": "/getRestDeInfo", "params": {"solYear": "2026", "_type": "json"}}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """가짜를 고르지 않은 시험이 부르면 599. 이름 풀이는 늘 공인 IP."""
    monkeypatch.setattr(generic, "TRANSPORT", ApiMock((599, {})))
    monkeypatch.setattr(generic, "RESOLVE", info_doubles.public)


@pytest.fixture
def api(monkeypatch) -> ApiMock:
    mock = ApiMock()
    monkeypatch.setattr(generic, "TRANSPORT", mock)
    return mock


def _row(session, **over) -> InfoConnection:
    values = {"name": "공휴일", "preset": "generic", "base_url": BASE, "secret_ciphertext": encrypt(KEY),
              "secret_last4": KEY[-4:], "status": "ok", "description": "공휴일·대체공휴일(연·월별)",
              "usage": "/getRestDeInfo?solYear=YYYY&_type=json", "key_in": "query", "key_name": "ServiceKey"}
    row = InfoConnection(**(values | over))
    session.add(row)
    session.commit()
    return row


@pytest.fixture
def holidays(session) -> InfoConnection:
    return _row(session)


def _args(row: InfoConnection, **over) -> dict:
    return ARGS | {"connection_id": row.id} | over


@pytest.fixture
def ctx_chat(session, ctx):
    chat = chats.create_chat(session, user_id=ctx.user.id)
    chats.add_message(session, chat.id, "user", {"kind": "text", "text": "12월 공휴일 빼고 일정 봐 줘"})
    session.commit()
    return dataclasses.replace(ctx, chat_session_id=chat.id)


def _leaks(text: str) -> list[str]:
    return [s for s in SECRETS if s in text]


def test_tools_are_registered():
    specs = {t.name: t for t in list_tools()}
    assert not specs["info.list"].mutates and specs["info.call"].mutates
    assert "4번" in specs["info.call"].description and "info__list" in specs["info.call"].description


# ── info.list ───────────────────────────────────────────────────────


async def test_list_shows_usable_connections_without_key_material(session, ctx):
    weather = _row(session, name="기상청", preset="kma", base_url=kma.DEFAULT_BASE_URL, description="", usage="",
                   key_name="serviceKey")
    row = _row(session, status="unknown")
    _row(session, name="키를 못 읽음", secret_ciphertext="not-a-fernet-token")
    r = await call("info.list", {}, ctx)
    assert r.ok, r.error
    found = r.output["connections"]
    assert [(c["id"], c["name"], c["kind"], c["status"]) for c in found] == [
        (weather.id, "기상청", "kma", "ok"), (row.id, "공휴일", "generic", "unknown")]
    assert set(found[1]) == {"id", "name", "kind", "description", "status", "usage_chars", "usage"}
    assert (found[1]["description"], found[1]["usage"]) == ("공휴일·대체공휴일(연·월별)", None)  # 쓰는 법은 하나씩
    assert found[1]["usage_chars"] == len(row.usage) and found[0]["description"]
    text = json.dumps(r.output, ensure_ascii=False)
    assert not _leaks(text) and KEY[-4:] not in text and row.secret_ciphertext not in text


async def test_list_is_empty_without_connections(ctx):
    assert (await call("info.list", {}, ctx)).output == {"connections": [], "more": 0, "hint": None}


# ── info.call ───────────────────────────────────────────────────────


async def test_call_returns_the_body_and_keeps_it_as_evidence(api, holidays, ctx, events, session):
    r = await call("info.call", _args(holidays), ctx)
    assert r.ok, r.error
    out = r.output
    assert set(out) == {"ok", "http_status", "content_type", "body", "truncated", "evidence_id"}
    assert (out["ok"], out["http_status"], out["truncated"]) == (True, 200, False)
    assert "application/json" in out["content_type"] and json.loads(out["body"]) == info_doubles.holiday_body()
    [sent] = api.requests
    assert sent.method == "GET" and f"ServiceKey={KEY_ENCODED}&solYear=2026&_type=json" in sent.url.query.decode()

    item = session.get(EvidenceItem, out["evidence_id"])
    row = session.get(EvidenceSearch, item.search_id)
    assert (row.mode, row.ok, row.result_count, row.error_code) == ("info", True, 1, None)
    assert item.title == "공휴일 /getRestDeInfo" and item.hostname == HOST
    assert item.url == f"{BASE}/getRestDeInfo?solYear=2026&_type=json" and "기독탄신일" in item.description
    card = events[-1]
    assert card.type == "card" and card.data["kind"] == "evidence" and card.data["mode"] == "info"
    assert card.data["results"] == [{"evidence_id": item.id, "title": item.title, "url": item.url,
                                     "hostname": HOST, "date": None}]


async def test_numbers_in_params_are_sent_as_text(api, holidays, ctx):
    r = await call("info.call", _args(holidays, params={"solYear": 2026, "solMonth": 12}), ctx)
    assert r.ok, r.error
    assert "solYear=2026&solMonth=12" in api.requests[0].url.query.decode()


async def test_kma_connection_points_to_info_weather(api, session, ctx):
    row = _row(session, name="기상청", preset="kma", base_url=kma.DEFAULT_BASE_URL)
    r = await call("info.call", _args(row), ctx)
    assert not r.ok and "info__weather" in r.error and api.requests == []


async def test_unknown_connection(api, ctx):
    r = await call("info.call", ARGS | {"connection_id": 999}, ctx)
    assert not r.ok and "info__list" in r.error and api.requests == []


@pytest.mark.parametrize("path", ["getRestDeInfo", "https://evil.example/x", "//evil.example/x", "/a/../b",
                                  "/a@evil.example", "/a\\b", "/a\r\nb", "/x?servicekey=abc"])
async def test_bad_path_is_refused_in_korean_before_any_request(api, holidays, ctx, session, path):
    r = await call("info.call", _args(holidays, path=path), ctx)
    assert not r.ok and any("가" <= ch <= "힣" for ch in r.error) and api.requests == []


async def test_key_name_in_params_is_refused(api, holidays, ctx):
    r = await call("info.call", _args(holidays, params={"SERVICEKEY": "x"}), ctx)
    assert not r.ok and "키" in r.error and api.requests == []


async def test_a_failure_is_recorded_even_after_rollback(api, holidays, ctx, session):
    api.answer = (200, gateway_body("30"))
    r = await call("info.call", _args(holidays), ctx)
    assert not r.ok and r.error.startswith(kma.FAILED_MESSAGES["not_registered"].replace("기상청", "공휴일"))
    session.rollback()  # 루프는 실패한 도구의 쓰기를 버린다
    row = session.scalars(select(EvidenceSearch)).one()
    assert (row.mode, row.ok, row.error_code, row.result_count) == ("info", False, "not_registered", 0)


async def test_internal_host_at_call_time_is_recorded_and_not_sent(api, holidays, ctx, session, monkeypatch):
    monkeypatch.setattr(generic, "RESOLVE", lambda host, port: ["127.0.0.1"])
    r = await call("info.call", _args(holidays), ctx)
    assert not r.ok and "내부망" in r.error and api.requests == []
    assert session.scalars(select(EvidenceSearch)).one().error_code == "blocked_host"


async def test_long_body_is_cut_with_a_hint(api, holidays, ctx, session):
    api.answer = (200, {"items": ["가" * 9000]})
    r = await call("info.call", _args(holidays), ctx)
    assert r.ok and r.output["truncated"] is True
    assert len(r.output["body"]) <= 3500 and r.output["body"].endswith(generic.TRUNCATED_HINT)
    assert len(session.get(EvidenceItem, r.output["evidence_id"]).description) <= 3500


async def test_four_per_request_counting_failures_apart_from_weather_and_search(api, holidays, ctx_chat, session):
    for mode in ("weather", "weather", "weather", "web", "web"):  # 날씨·근거 검색은 따로 센다
        session.add(EvidenceSearch(chat_session_id=ctx_chat.chat_session_id, query="q", mode=mode, ok=True))
    session.commit()
    api.answer = lambda request: (500, {}) if request.url.path.endswith("/fail") else (200, {"ok": 1})
    results = []
    for path in ("/fail", "/getRestDeInfo", "/fail", "/getRestDeInfo"):
        results.append(await call("info.call", _args(holidays, path=path), ctx_chat))
        session.commit()  # 루프처럼 도구마다 commit
    assert [x.ok for x in results] == [False, True, False, True]
    r = await call("info.call", _args(holidays), ctx_chat)
    assert not r.ok and r.error == LIMIT_MESSAGE and len(api.requests) == 4
    chat = ctx_chat.chat_session_id
    assert searches_since(session, chat, None) == 2 and searches_since(session, chat, None, weather=True) == 3
    assert searches_since(session, chat, None, info=True) == 4


async def test_no_write_is_held_while_waiting_for_the_api(holidays, ctx_chat, monkeypatch):
    db = Settings().data_dir / "chronos.db"
    seen = []

    def answer(request):
        with closing(sqlite3.connect(db, timeout=0)) as other:  # 다른 연결이 바로 쓸 수 있어야 한다
            other.execute("BEGIN IMMEDIATE")
            other.rollback()
        seen.append(True)
        return 200, {"ok": 1}

    monkeypatch.setattr(generic, "TRANSPORT", ApiMock(answer))
    r = await call("info.call", _args(holidays), ctx_chat)
    assert r.ok, r.error
    assert seen == [True]


# ── 키가 어디에도 새지 않는다(에이전트 루프 전체) ───────────────────


@pytest.mark.parametrize(("key_in", "key_name"), [("query", "ServiceKey"), ("header", "Authorization")])
async def test_planted_key_appears_nowhere(session, holidays, caplog, monkeypatch, key_in, key_name):
    caplog.set_level(logging.DEBUG)
    holidays.key_in, holidays.key_name = key_in, key_name
    session.commit()

    def answer(request):
        if request.url.path.endswith("/boom"):
            raise RuntimeError(f"boom {request.url} {KEY}")
        if request.url.path.endswith("/down"):
            raise httpx.ConnectError(f"cannot reach {request.url}")
        return 200, {"echo": KEY, "echo2": KEY_ENCODED, "echo3": KEY_ENCODED.lower(), "url": str(request.url),
                     "headers": dict(request.headers), "items": [{"dateName": "기독탄신일"}]}

    monkeypatch.setattr(generic, "TRANSPORT", ApiMock(answer))
    add_connection(session)
    owner = session.scalars(select(User).where(User.login_id == "admin")).one()
    chat = chats.create_chat(session, user_id=owner.id)
    llm = ScriptedLlm([
        calls("info.call", _args(holidays), call_id="c1"),
        calls("info.call", _args(holidays, path="/boom"), call_id="c2"),
        calls("info.call", _args(holidays, path="/down"), call_id="c3"),
        reply("12월 25일이 공휴일입니다."),
    ])
    client = LlmClient(session, transport=llm.transport)
    events = [e async for e in run_turn(session, owner, chat.id, "12월 공휴일 알려줘", UiContext(None, None, None),
                                        llm=client)]
    session.expire_all()
    steps = session.scalars(select(WorkflowStep).order_by(WorkflowStep.id)).all()
    assert [s.status for s in steps] == ["done", "failed", "failed"]
    assert "기독탄신일" in steps[0].output_json  # 본문은 에이전트에게 갔다

    stored = [json.dumps(m.content_json, ensure_ascii=False) for m in session.scalars(select(ChatMessage))]
    stored += [f"{s.input_json} {s.output_json}" for s in steps]
    stored += [f"{t.input_text} {t.output_text} {t.error}" for t in session.scalars(select(TraceEvent))]
    stored += [f"{i.title} {i.url} {i.hostname} {i.description} {i.extra_json}"
               for i in session.scalars(select(EvidenceItem))]
    stored += [f"{s.query} {s.error_code}" for s in session.scalars(select(EvidenceSearch))]
    stored += [json.dumps(e.data, ensure_ascii=False, default=str) for e in events]
    stored += [json.dumps(llm.last_body, ensure_ascii=False), caplog.text]
    for text in stored:
        assert not _leaks(text), text[:300]
    assert "HTTP Request: GET https://apis.data.go.kr" in caplog.text


# ── 보안 검토 반영(1차) ─────────────────────────────────────────────


async def test_list_one_connection_gives_its_usage(session, ctx):
    weather = _row(session, name="기상청", preset="kma", base_url=kma.DEFAULT_BASE_URL, usage="")
    row = _row(session)
    r = await call("info.list", {"connection_id": row.id}, ctx)
    assert r.ok, r.error
    [one] = r.output["connections"]
    assert (one["id"], one["usage"], one["usage_chars"]) == (row.id, row.usage, len(row.usage))
    [kma_row] = (await call("info.list", {"connection_id": weather.id}, ctx)).output["connections"]
    assert "info__weather" in kma_row["usage"]
    r = await call("info.list", {"connection_id": 999}, ctx)
    assert not r.ok and "info__list" in r.error


async def test_list_of_the_five_real_templates_fits_the_tool_result(session, ctx):
    for t in templates.load_templates():
        _row(session, name=t.label, base_url=t.base_url, description=t.description, usage=t.usage,
             key_name=t.key_name, test_path=t.test_path)
    r = await call("info.list", {}, ctx)
    text = result_text(r, limit=4000)
    assert len(json.dumps(r.output, ensure_ascii=False)) < 4000 and not text.endswith(CUT_NOTE)
    assert len(r.output["connections"]) == 5


async def test_list_scrubs_a_key_already_stored_in_the_notes(session, ctx):
    row = _row(session, name=f"공휴일 {KEY[:4]}", description=f"키 {KEY_ENCODED}",
               usage=f"예: {BASE}/getRestDeInfo?ServiceKey={KEY.replace('+', '%2B')}&solYear=2026")
    for args in ({}, {"connection_id": row.id}):
        r = await call("info.list", args, ctx)
        assert r.ok and not _leaks(json.dumps(r.output, ensure_ascii=False))


def _holidays(n: int) -> dict:
    items = [{"dateKind": "01", "dateName": "기독탄신일", "isHoliday": "Y", "locdate": 20261225 + i, "seq": 1}
             for i in range(n)]
    return {"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                         "body": {"items": {"item": items}, "numOfRows": n, "pageNo": 1, "totalCount": n}}}


async def test_a_quote_heavy_body_keeps_evidence_id_inside_the_tool_result(api, holidays, ctx):
    api.answer = (200, _holidays(60))
    r = await call("info.call", _args(holidays), ctx)
    assert r.ok and r.output["truncated"] is True
    keys = list(r.output)
    assert keys.index("evidence_id") < keys.index("body") and keys.index("truncated") < keys.index("body")
    text = result_text(r, limit=4000)
    assert not text.endswith(CUT_NOTE) and json.loads(text)["evidence_id"] == r.output["evidence_id"]


async def test_param_names_and_values_are_capped(api, holidays, ctx):
    r = await call("info.call", _args(holidays, params={"k" * 101: "v"}), ctx)
    assert not r.ok and r.error.startswith("입력 형식 오류")
    r = await call("info.call", _args(holidays, params={"q": "가" * 501}), ctx)
    assert not r.ok and r.error.startswith("입력 형식 오류")
    r = await call("info.call", _args(holidays, params={f"p{i}": "1" for i in range(31)}), ctx)
    assert not r.ok and r.error.startswith("입력 형식 오류") and api.requests == []


async def test_a_url_too_long_to_build_is_a_korean_bad_path_and_not_counted(api, holidays, ctx_chat, session, caplog):
    r = await call("info.call", _args(holidays, params={f"p{i}": "가" * 500 for i in range(30)}), ctx_chat)
    assert not r.ok and any("가" <= ch <= "힣" for ch in r.error) and "도구 실행 중 오류" not in r.error
    assert api.requests == [] and "Traceback" not in caplog.text
    assert searches_since(session, ctx_chat.chat_session_id, None, info=True) == 0


async def test_argument_errors_are_not_counted(api, holidays, ctx_chat, session):
    weather = _row(session, name="기상청", preset="kma", base_url=kma.DEFAULT_BASE_URL)
    bad = [_args(holidays, path="//evil.example"), _args(holidays, params={"servicekey": "x"}),
           ARGS | {"connection_id": 999}, _args(weather), _args(holidays, path="/a/%2e%2e/b")]
    for args in bad:
        assert not (await call("info.call", args, ctx_chat)).ok
    assert searches_since(session, ctx_chat.chat_session_id, None, info=True) == 0 and api.requests == []
    for _ in range(4):
        assert (await call("info.call", _args(holidays), ctx_chat)).ok
        session.commit()
    assert (await call("info.call", _args(holidays), ctx_chat)).error == LIMIT_MESSAGE


async def test_a_failed_call_shows_the_status_and_the_start_of_the_body(api, holidays, ctx):
    api.answer = (500, f"필수 파라미터 solYear 누락 (key={KEY})", {"content-type": "text/plain"})
    r = await call("info.call", _args(holidays), ctx)
    assert not r.ok and "HTTP 500" in r.error and "필수 파라미터 solYear 누락" in r.error and not _leaks(r.error)


# ── 재검토 작은 지적 ─────────────────────────────────────────────────


async def test_an_unexpected_error_after_sending_is_a_counted_korean_failure(holidays, ctx_chat, session, monkeypatch):
    async def broken(conn, path, params):
        raise RuntimeError(f"boom {KEY}")

    monkeypatch.setattr(generic, "fetch", broken)
    r = await call("info.call", _args(holidays), ctx_chat)
    assert not r.ok and "RuntimeError" not in r.error and not _leaks(r.error)
    assert any("가" <= ch <= "힣" for ch in r.error)
    session.rollback()
    row = session.scalars(select(EvidenceSearch)).one()
    assert (row.mode, row.ok, row.error_code) == ("info", False, "unknown")


async def test_list_of_twenty_long_connections_fits_with_a_more_count(session, ctx):
    for i in range(20):
        _row(session, name=f"연결 {i}", description="가" * 500)
    r = await call("info.list", {}, ctx)
    assert r.ok, r.error
    out = r.output
    assert len(json.dumps(out, ensure_ascii=False)) < 4000 and not result_text(r, limit=4000).endswith(CUT_NOTE)
    assert all(len(c["description"]) <= 120 for c in out["connections"])
    assert len(out["connections"]) + out["more"] == 20 and out["more"] > 0 and "connection_id" in out["hint"]


async def test_a_short_list_has_no_more_and_no_hint(session, ctx):
    _row(session)
    out = (await call("info.list", {}, ctx)).output
    assert (out["more"], out["hint"]) == (0, None)


async def test_one_connection_with_a_long_quoted_usage_fits(session, ctx):
    usage = ('예: /getX?a=1&b="값"\n' * 200)[:3000]
    row = _row(session, name="가" * 100, description="가" * 500, usage=usage)
    r = await call("info.list", {"connection_id": row.id}, ctx)
    assert r.ok and len(json.dumps(r.output, ensure_ascii=False)) < 4000
    [one] = r.output["connections"]
    assert one["usage_chars"] == 3000 and one["usage"].startswith('예: /getX?a=1&b="값"') and len(one["usage"]) < 3000
