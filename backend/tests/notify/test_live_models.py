"""구글 Live 모델 목록(app.notify.live_models) — 고침 2(Task 113): Live 모델은 v1alpha 에만 보이고, 우리가 보내지 않는 설정이 필요한
모델(`-extended-thinking`)과 받아쓰기만 하는 모델(`transcribe`)은 고를 수 없다. 구글은 부르지 않는다(가짜 클라이언트·가짜 모듈)."""

import sys
from types import SimpleNamespace

import google
import pytest

from app.notify import live_models
from app.outreach.voice import numbers

LIVE = live_models.LIVE_ACTION


def model(name: str, *actions: str) -> SimpleNamespace:
    return SimpleNamespace(name=f"models/{name}", supported_actions=list(actions))


def client_of(items: list):
    def make(key: str, timeout_s: float):
        return SimpleNamespace(models=SimpleNamespace(list=lambda *, config=None: SimpleNamespace(page=items)))
    return make


def test_google_live_api_version_is_one_shared_constant():
    assert numbers.GOOGLE_LIVE_API_VERSION == "v1alpha"


def test_list_client_asks_the_v1alpha_api(monkeypatch):
    """기본(v1beta)에는 Live 모델이 없다(11-24 실측: 28개 중 0) — v1alpha 로 물어야 Live 모델이 보인다."""
    made: list[dict] = []
    fake_types = SimpleNamespace(HttpOptions=lambda **kw: kw, HttpRetryOptions=lambda **kw: kw)
    fake_genai = SimpleNamespace(Client=lambda **kw: made.append(kw) or kw, types=fake_types)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    monkeypatch.setattr(google, "genai", fake_genai, raising=False)
    live_models.google_client("goog-test-key-QQQQ7777", 8)
    options = made[0]["http_options"]
    assert options["api_version"] == numbers.GOOGLE_LIVE_API_VERSION and options["timeout"] == 8000
    assert options["retry_options"] == {"attempts": 1}


def test_models_that_need_unsent_config_or_cannot_speak_are_not_offered():
    items = [model("gemini-3.8-live", LIVE), model("gemini-3.8-live-extended-thinking", LIVE),
             model("gemini-3.1-flash-live-preview", LIVE), model("gemini-2.5-flash-transcribe-live", LIVE),
             model("gemini-2.5-flash-native-audio-preview", LIVE), model("gemini-3.8-flash", "generateContent")]
    found = live_models.list_live_models("goog-test-key-QQQQ7777", client=client_of(items))
    assert found.models == ("gemini-3.8-live", "gemini-3.1-flash-live-preview", "gemini-2.5-flash-native-audio-preview")
    assert found.available == frozenset(found.models) and not found.fallback


def test_fallback_offers_only_models_we_can_call():
    assert live_models.FALLBACK == (numbers.DEFAULT_LIVE_MODEL,)
    assert all(live_models.usable(name) for name in live_models.FALLBACK)


@pytest.mark.parametrize("name", ["gemini-3.8-live-extended-thinking", "gemini-2.5-flash-transcribe-live",
                                  "gemini-live-transcribe"])
def test_unusable_names(name):
    assert not live_models.usable(name)
