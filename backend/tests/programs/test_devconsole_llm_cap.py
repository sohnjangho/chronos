"""개발 콘솔: 하루 LLM 비용 상한 읽기·바꾸기(관리자만), 환경 변수로 정했으면 못 바꿈, 사용량 탭의 오늘 쓴 돈."""

import pytest

from app.llm import daily_cap
from app.store.tables import LlmCall

PATH = "/api/devconsole/llm-cap"


@pytest.fixture(autouse=True)
def no_env(monkeypatch):
    monkeypatch.delenv(daily_cap.ENV, raising=False)


def _spend(session, cost):
    session.add(LlmCall(purpose="normal", model="m", requested_model="m", routing_strategy=None, cost=cost,
                        cost_estimated=True, latency_ms=1, ok=True))
    session.commit()


def test_default_off_then_set_and_clear(client, admin, session):
    _spend(session, 0.25)
    assert client.get(PATH, headers=admin).json() == {"cap_usd": None, "fixed_by_env": False, "spent_today_usd": 0.25}
    r = client.put(PATH, headers=admin, json={"cap_usd": 10})
    assert r.status_code == 200 and r.json()["cap_usd"] == 10.0
    assert client.get(PATH, headers=admin).json()["cap_usd"] == 10.0
    assert client.put(PATH, headers=admin, json={"cap_usd": None}).json()["cap_usd"] is None


@pytest.mark.parametrize("bad", [0, -1, "abc", 1e9])
def test_bad_values_are_refused(client, admin, bad):
    assert client.put(PATH, headers=admin, json={"cap_usd": bad}).status_code == 422


def test_admin_only(client, user):
    assert client.get(PATH, headers=user).status_code == 403
    assert client.put(PATH, headers=user, json={"cap_usd": 1}).status_code == 403


def test_env_fixes_the_cap(client, admin, monkeypatch):
    monkeypatch.setenv(daily_cap.ENV, "5")
    assert client.get(PATH, headers=admin).json() == {"cap_usd": 5.0, "fixed_by_env": True, "spent_today_usd": 0.0}
    r = client.put(PATH, headers=admin, json={"cap_usd": 20})
    assert r.status_code == 409 and r.json()["code"] == "fixed_by_env"


def test_usage_carries_today_and_cap(client, admin, session):
    _spend(session, 1.5)
    client.put(PATH, headers=admin, json={"cap_usd": 10})
    u = client.get("/api/devconsole/usage", headers=admin).json()
    assert u["llm_cap"] == {"cap_usd": 10.0, "fixed_by_env": False, "spent_today_usd": 1.5}
