"""AI 전화가 실제로 쓰는 번호와 모델의 규칙 — 설정 길(notify_settings.voice)과 통화 실행(outreach.voice.runner)이 같이 쓴다.

- 번호: 음성 설정의 AI 전화 번호(`voice_settings.agent_number`), 비었으면 알림 연결의 발신번호(`sender_number`) — PM 11-24.
- 모델: 구글(Gemini Live)은 빈 값이면 `DEFAULT_LIVE_MODEL`. SDK 의 기본 모델(gemini-3.1-flash-live-preview)은 2026-11-17 에
  구글이 내렸다(Live 연결이 HTTP 404). 다른 공급자는 그대로(빈 값 = SDK 기본).
- 받아쓰기 언어(11-24 ASR 보고서): 구글 세션의 SDK `language=` 는 원격 측정 값일 뿐이고(받아쓰기에 쓰이지 않는다), 받아쓰기는
  `input_audio_transcription` 을 그대로 Live 설정에 넣는다 — google-genai `AudioTranscriptionConfig.language_codes`(BCP-47,
  「비우면 자동 감지」). `google_transcription(언어, 낱말)` 가 그 값을 준다. OpenAI 는 SDK 가 `language=` 를 받아쓰기 언어로 이미 쓴다.
- 받아쓰기 낱말(11-24): 같은 설정의 `custom_vocabulary`(SDK 의 `adaptation_phrases` 는 폐기 표시라 쓰지 않는다) — 통화 명세의
  `CallSpec.vocabulary`(site_name.vocabulary 가 지음). v1alpha 가 이 칸을 받는 것은 관리자가 실제 키로(통화 없이) 확인했다.
"""

from collections.abc import Sequence
from typing import Literal

from app.outreach import languages

DEFAULT_LIVE_MODEL = "gemini-3.8-live"  # 구글 폐기 안내가 적은 뒤이음 모델
# 구글 Live 모델은 v1alpha 에만 보이고 붙는다(11-24 실측: 기본 v1beta 는 목록에 Live 0개 · Live 소켓 404, v1alpha 는 목록 65개 ·
# gemini-3.8-live 연결 됨). 목록(live_models)·진단·어댑터가 이 하나를 쓴다. OpenAI 에는 쓰지 않는다.
GOOGLE_LIVE_API_VERSION = "v1alpha"
LIVE_LANGUAGE_CODES = {"ko": "ko-KR", "en": "en-US"}  # 통화 언어 → 구글 받아쓰기 언어(BCP-47). 없는 언어는 자동 감지


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


def google_transcription(language: str, vocabulary: Sequence[str] = ()) -> dict:
    """구글 Live 세션의 `input_audio_transcription`: 통화 언어의 받아쓰기 언어(표에 없는 언어는 넣지 않음 = SDK 기본 자동 감지)와,
    낱말이 있으면 `custom_vocabulary`(받아쓰기가 그 낱말 쪽으로 기울게 — 현장·작업 이름, site_name.vocabulary)."""
    code = LIVE_LANGUAGE_CODES.get(languages.code(language))
    out: dict = {"language_codes": [code]} if code else {}
    if vocabulary:
        out["custom_vocabulary"] = list(vocabulary)
    return out
