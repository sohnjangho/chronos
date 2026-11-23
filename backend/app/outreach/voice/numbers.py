"""AI 전화가 실제로 쓰는 번호와 모델의 규칙 — 설정 길(notify_settings.voice)과 통화 실행(outreach.voice.runner)이 같이 쓴다.

- 번호: 음성 설정의 AI 전화 번호(`voice_settings.agent_number`), 비었으면 알림 연결의 발신번호(`sender_number`) — PM 11-24.
- 모델: 구글(Gemini Live)은 빈 값이면 `DEFAULT_LIVE_MODEL`. SDK 의 기본 모델(gemini-3.1-flash-live-preview)은 2026-11-17 에
  구글이 내렸다(Live 연결이 HTTP 404). 다른 공급자는 그대로(빈 값 = SDK 기본).
"""

from typing import Literal

DEFAULT_LIVE_MODEL = "gemini-3.8-live"  # 구글 폐기 안내가 적은 뒤이음 모델
# 구글 Live 모델은 v1alpha 에만 보이고 붙는다(11-24 실측: 기본 v1beta 는 목록에 Live 0개 · Live 소켓 404, v1alpha 는 목록 65개 ·
# gemini-3.8-live 연결 됨). 목록(live_models)·진단·어댑터가 이 하나를 쓴다. OpenAI 에는 쓰지 않는다.
GOOGLE_LIVE_API_VERSION = "v1alpha"


def effective_agent_number(conn: object, voice: object | None) -> str | None:
    """AI 전화에 쓸 번호(정리한 숫자 꼴): 음성 설정의 번호, 없으면 알림 연결의 발신번호, 둘 다 없으면 None."""
    own = getattr(voice, "agent_number", None) if voice is not None else None
    if isinstance(own, str) and own:
        return own
    sender = getattr(conn, "sender_number", None)
    return sender if isinstance(sender, str) and sender else None


def agent_number_source(conn: object, voice: object | None) -> Literal["voice", "connection"] | None:
    """`effective_agent_number` 가 어디서 왔는가: 음성 설정("voice") · 알림 연결("connection") · 없음(None)."""
    number = effective_agent_number(conn, voice)
    if number is None:
        return None
    return "voice" if number == getattr(voice, "agent_number", None) else "connection"


def effective_model(provider: str, model: str | None) -> str | None:
    """SDK 에 넘길 모델 이름. 구글은 빈 값이면 `DEFAULT_LIVE_MODEL`, 다른 공급자는 빈 값이면 None(SDK 기본)."""
    if model:
        return model
    return DEFAULT_LIVE_MODEL if provider == "google" else None
