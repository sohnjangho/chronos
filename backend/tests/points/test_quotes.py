"""관리 포인트 위험 줄의 근거 문장: 뒤에서 채운다(pending → ready|failed). 부른 쪽을 막지 않는다. 진짜 Liner 는 부르지 않는다."""

import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from app.db import current_engine
from app.llm import search_agent
from app.llm.search_agent import FAKE_QUOTE, AgentQuote
from app.points import quotes
from app.store.tables import LlmCall
from tests.llm_doubles import KEY, add_connection

OK_BODY = {"references": [{"title": "기상 특보 기준", "url": "https://weather.example.go.kr/a"}],
           "chunks": [{"type": "data-search-chunks",
                       "data": {"referenceChunks": [{"num": 1, "content": "호우주의보는 3시간 60mm 이상일 때 낸다.",
                                                         "sourceTitle": "기상 특보 기준",
                                                         "sourceUrl": "https://weather.example.go.kr/a"}]}}]}
KEY_ARGS = (7, 3, "A120", "weather")


@pytest.fixture
def conn(session):
    c = add_connection(session)
    session.commit()
    return c


def answer(monkeypatch, body: object = OK_BODY, gate: asyncio.Event | None = None, on_request=None) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if on_request is not None:
            on_request()
        if gate is not None:
            await gate.wait()
        if isinstance(body, str):
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=body)

    monkeypatch.setattr(search_agent, "TRANSPORT", httpx.MockTransport(handle))
    return seen


def state(session, *key):
    session.expire_all()
    return quotes.get(session, *(key or KEY_ARGS))


async def test_fill_returns_at_once_then_ready(session, conn, monkeypatch):
    gate = asyncio.Event()
    seen = answer(monkeypatch, gate=gate)
    task = await quotes.fill(*KEY_ARGS, question="골조 타설 기간 비 예보")
    assert task is not None
    got = state(session)
    assert (got.status, got.quotes, got.message) == ("pending", [], "근거 문장 찾는 중")
    gate.set()
    await task
    got = state(session)
    assert got.status == "ready" and got.message == ""
    assert got.quotes == [AgentQuote("호우주의보는 3시간 60mm 이상일 때 낸다.", "https://weather.example.go.kr/a", "기상 특보 기준")]
    assert json.loads(seen[0].content)["messages"][0]["content"] == "골조 타설 기간 비 예보"


async def test_no_db_connection_is_held_while_waiting(session, conn, monkeypatch):
    session.close()
    pool = current_engine().pool
    held: list[int] = []
    gate = asyncio.Event()
    answer(monkeypatch, gate=gate, on_request=lambda: held.append(pool.checkedout()))
    task = await quotes.fill(*KEY_ARGS, question="q")
    while not held:
        await asyncio.sleep(0.01)
    assert held == [0] and pool.checkedout() == 0  # 기다리는 동안 풀에서 빌린 연결이 없다
    gate.set()
    await task
    assert pool.checkedout() == 0


async def test_at_most_three_at_once(session, conn, monkeypatch):
    gate = asyncio.Event()
    seen = answer(monkeypatch, gate=gate)
    tasks = [await quotes.fill(7, 3, f"A{n}", "weather", question="q") for n in range(5)]
    for _ in range(50):
        await asyncio.sleep(0.01)
    assert len(seen) == quotes.MAX_CONCURRENT == 3
    gate.set()
    await asyncio.gather(*tasks)
    assert len(seen) == 5 and all(state(session, 7, 3, f"A{n}", "weather").status == "ready" for n in range(5))


async def test_data_error_ends_failed(session, conn, monkeypatch):
    answer(monkeypatch, "data: " + json.dumps({"type": "data-error", "data": {"message": KEY}}) + "\n\ndata: [DONE]\n\n")
    await (await quotes.fill(*KEY_ARGS, question="q"))
    got = state(session)
    assert (got.status, got.quotes, got.error_code) == ("failed", [], "agent_error")
    assert got.message == "근거 문장을 찾지 못했습니다"
    assert KEY not in str(vars(session.get(quotes.PointQuote, KEY_ARGS)))


async def test_time_limit_ends_failed(session, conn, monkeypatch):
    answer(monkeypatch, gate=asyncio.Event())  # 끝내 답하지 않는다
    monkeypatch.setattr(quotes, "TIMEOUT_S", 0.05)
    await (await quotes.fill(*KEY_ARGS, question="q"))
    got = state(session)
    assert (got.status, got.error_code) == ("failed", "timeout")


async def test_no_connection_ends_failed(session, monkeypatch):
    seen = answer(monkeypatch)
    await (await quotes.fill(*KEY_ARGS, question="q"))
    assert state(session).error_code == "no_connection" and seen == []


async def test_ready_and_pending_are_not_asked_again(session, conn, monkeypatch):
    gate = asyncio.Event()
    seen = answer(monkeypatch, gate=gate)
    first = await quotes.fill(*KEY_ARGS, question="q")
    assert await quotes.fill(*KEY_ARGS, question="q") is None  # 찾는 중
    gate.set()
    await first
    assert await quotes.fill(*KEY_ARGS, question="q", retry=True) is None  # 채워짐은 retry 여도 다시 안 부른다
    assert len(seen) == 1


async def test_failed_is_asked_again_only_with_retry(session, conn, monkeypatch):
    key = (7, 3, "A130", "materials")
    answer(monkeypatch, "data: [DONE]\n\n")
    await (await quotes.fill(*key, question="q"))
    assert state(session, *key).status == "failed"
    seen = answer(monkeypatch)
    assert await quotes.fill(*key, question="q") is None and seen == []  # 실패 뒤 저절로 다시 부르지 않는다
    await (await quotes.fill(*key, question="q", retry=True))  # 「다시 찾기」
    assert state(session, *key).status == "ready" and len(seen) == 1


async def test_stale_pending_reads_failed_and_needs_retry(session, conn, monkeypatch):
    seen = answer(monkeypatch)
    session.add(quotes.PointQuote(schedule_id=7, version=3, activity_id="A120", kind="weather", status="pending",
                                  quotes_json=[], updated_at=datetime.now(UTC) - quotes.STALE_AFTER))
    session.commit()
    got = state(session)
    assert (got.status, got.error_code, got.message) == ("failed", "stale", "근거 문장을 찾지 못했습니다")
    assert await quotes.fill(*KEY_ARGS, question="q") is None and seen == []
    await (await quotes.fill(*KEY_ARGS, question="q", retry=True))
    assert state(session).status == "ready"


async def test_save_failure_still_ends_failed(session, conn, monkeypatch):
    answer(monkeypatch)
    real = quotes._save

    def broken(key, status, found, code):
        if status == "ready":
            raise RuntimeError("디스크")
        real(key, status, found, code)

    monkeypatch.setattr(quotes, "_save", broken)
    await (await quotes.fill(*KEY_ARGS, question="q"))
    got = state(session)
    assert (got.status, got.error_code) == ("failed", "save_error")


def test_fill_outside_a_running_loop_writes_nothing(session, conn):
    coro = quotes.fill(*KEY_ARGS, question="q")
    with pytest.raises(RuntimeError):
        coro.send(None)  # 루프 없이 몰면 get_running_loop 가 먼저 실패한다
    assert state(session) is None


async def test_fake_llm_gives_a_fixed_quote_without_cost(session, monkeypatch):
    monkeypatch.setenv("CHRONOS_FAKE_LLM", "1")
    monkeypatch.setattr(search_agent, "TRANSPORT", None)
    await (await quotes.fill(*KEY_ARGS, question="q"))  # 연결이 없어도
    got = state(session)
    assert got.status == "ready" and got.quotes == [FAKE_QUOTE]
    assert session.scalars(select(LlmCall)).all() == []


async def test_unknown_is_none_and_keys_are_separate(session, conn, monkeypatch):
    answer(monkeypatch)
    assert quotes.get(session, *KEY_ARGS) is None
    await (await quotes.fill(*KEY_ARGS, question="q"))
    assert state(session, 7, 4, "A120", "weather") is None
    assert state(session, 7, 3, "A120", "fx") is None
