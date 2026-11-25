"""임베딩(app.llm.embeddings, Task 48): 배정 모델·64개씩·기록·긴 글 자르기·실패 code·키가 새지 않음."""

import logging

import httpx
import pytest
from sqlalchemy import select, text

from app.llm import embeddings, fake
from app.llm.embeddings import EmbedFailed, embed
from app.store.tables import LlmAssignment, LlmCall
from tests.embed_doubles import COST, LARGE, SMALL, FakeEmbedder, body, vector
from tests.llm_doubles import KEY, LINER


@pytest.fixture
def embedder(monkeypatch) -> FakeEmbedder:
    double = FakeEmbedder()
    monkeypatch.setattr(embeddings, "TRANSPORT", double.transport)
    return double


async def test_embed_uses_assigned_model_in_batches_of_64(session, connection, embedder):
    texts = [f"철근 배근 {i}" for i in range(130)] + ["동절기 타설"]
    out = await embed(session, texts)
    assert [len(b["input"]) for b in embedder.bodies] == [64, 64, 3]
    assert embedder.models == [SMALL] * 3
    request = embedder.requests[0]
    assert request.method == "POST" and str(request.url) == f"{LINER}/embeddings"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert out == [vector(t, SMALL) for t in texts]  # 응답 data 는 거꾸로 와도 index 차례로


async def test_each_call_is_recorded_with_tokens_and_cost(session, connection, embedder):
    await embed(session, ["동절기 타설", "철근 배근"])
    call = session.scalars(select(LlmCall)).one()
    assert (call.purpose, call.requested_model, call.model) == ("embedding", SMALL, "text-embedding-3-small")
    assert (call.input_tokens, call.output_tokens, call.cost) == (len("동절기 타설") + len("철근 배근"), 0, COST)
    assert call.ok and call.error_code is None and call.chat_session_id is None



async def test_embedding_without_cost_is_recorded_as_estimate(session, connection, embedder):
    sent = body(["동절기 타설"], SMALL)
    del sent["usage"]["cost"]
    embedder.push(sent)
    await embed(session, ["동절기 타설"])
    call = session.scalars(select(LlmCall)).one()
    # 답한 이름(text-embedding-3-small)은 가격표에 없고, 요청한 단일 모델(openai/…)은 $0.02 / 1M
    assert call.cost == pytest.approx(len("동절기 타설") * 0.02 / 1e6) and call.cost_estimated is True


async def test_stored_assignment_and_model_argument(session, connection, embedder):
    session.add(LlmAssignment(purpose="embedding", connection_id=connection.id, model=LARGE, routing_strategy=None))
    session.commit()
    assert len((await embed(session, ["동절기"]))[0]) == 12
    await embed(session, ["동절기"], model=SMALL)  # 다시 넣기 중 검색은 옛 모델을 준다
    assert embedder.models == [LARGE, SMALL]


async def test_empty_input_sends_nothing(session, connection, embedder):
    assert await embed(session, []) == [] and embedder.requests == []


async def test_long_input_is_cut_with_a_note(session, connection, embedder, caplog):
    caplog.set_level(logging.INFO, logger="app.llm.embeddings")
    await embed(session, ["짧은 글", "가" * 5000])
    assert embedder.bodies[0]["input"] == ["짧은 글", "가" * 4096]  # 기본 8192 토큰 ÷ 2
    assert "2번째 글이 길어 앞 4096자만 넣습니다(원래 5000자)" in caplog.text


async def test_input_limit_follows_the_models_context_length(session, connection, embedder):
    connection.models_json = [{"id": SMALL, "context_length": 512, "endpoints": ["/v1/embeddings"]}]
    session.commit()
    await embed(session, ["나" * 300])
    assert embedder.bodies[0]["input"] == ["나" * 256]


async def test_no_connection_fails_without_sending(session, embedder):
    with pytest.raises(EmbedFailed) as e:
        await embed(session, ["동절기"])
    assert e.value.code == "no_connection" and embedder.requests == []
    assert e.value.message == embeddings.MESSAGES["no_connection"]


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        (httpx.Response(400), "bad_request"),
        (httpx.Response(401), "bad_key"),
        (httpx.Response(402), "no_credit"),
        (httpx.Response(403), "bad_key"),
        (httpx.Response(404), "bad_url"),
        (httpx.Response(429), "rate_limited"),
        (httpx.Response(503), "server_error"),
        (httpx.ConnectError("refused"), "bad_url"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.Response(200, text="not json"), "unknown"),
        ({"data": "nope"}, "unknown"),
        ({"data": [{"index": 0, "embedding": [1.0]}]}, "unknown"),  # 글 2개에 벡터 1개
        ({"data": [{"index": 0, "embedding": [1.0]}, {"index": 1, "embedding": [1.0, 0.0]}]}, "unknown"),  # 차원이 다름
        ({"data": [{"index": 0, "embedding": []}, {"index": 1, "embedding": []}]}, "unknown"),  # 빈 벡터
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
async def test_failures_become_embed_failed_with_task27_codes(session, connection, embedder, reply, code):
    embedder.push(reply)
    with pytest.raises(EmbedFailed) as e:
        await embed(session, ["동절기", "철근"])
    assert e.value.code == code and e.value.message == embeddings.MESSAGES[code]
    call = session.scalars(select(LlmCall)).one()
    assert (call.ok, call.error_code, call.purpose) == (False, code, "embedding")


async def test_embed_failed_carries_no_key(session, connection, embedder, caplog):
    caplog.set_level(logging.DEBUG)
    embedder.push(httpx.Response(401, json={"error": f"invalid key {KEY}"}), httpx.ConnectError(f"proxy saw {KEY}"))
    for _ in range(2):
        with pytest.raises(EmbedFailed) as e:
            await embed(session, ["동절기"])
        assert KEY not in str(e.value) and KEY not in repr(e.value)
        assert e.value.__cause__ is None and e.value.__context__ is None  # 요청(머리글)을 든 예외가 따라붙지 않는다
    assert KEY not in caplog.text
    assert KEY not in repr(session.execute(text("SELECT * FROM llm_calls")).all())


async def test_fake_llm_mode_never_leaves_the_machine(session, connection, monkeypatch):
    monkeypatch.setenv(fake.ENV, "1")
    monkeypatch.setattr(embeddings, "TRANSPORT", None)
    with pytest.raises(EmbedFailed) as e:  # 가짜 Liner 는 대화만 안다 — 쓸 수 없는 응답
        await embed(session, ["동절기"])
    assert e.value.code == "unknown"
