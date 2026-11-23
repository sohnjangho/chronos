"""이 음성 모델 키로 쓸 수 있는 구글 Live 모델(양방향 스트리밍 `bidiGenerateContent`) 목록 — 설정 화면의 고르기와 진단 전 확인.

- 구글 클라이언트(`google-genai`)로 **요청 한 번**: 목록의 첫 쪽만 읽고(다음 쪽으로 넘기지 않음), 짧은 시간 제한, 다시 시도 없음,
  돌려주는 수에 상한. 키는 쓰기 전에 `redact.add_secrets` 에 올린다.
- 무엇이 잘못되든 던지지 않고 작은 고정 목록(`FALLBACK`, `DEFAULT_LIVE_MODEL` 이 맨 앞)과 그 까닭(쉬운 한국어)을 돌려준다.
  예외 글은 읽지 않는다(키·계정이 들 수 있다) — 남기는 것은 까닭의 낱말뿐.
- `google-genai` 는 `google_client` 안에서만 불러온다(이 모듈을 불러와도 SDK 가 올라오지 않는다). `app/outreach/voice` 가 아니라
  여기(진단 쪽)에 두는 것은 그 패키지가 어디서도 SDK 를 import 하지 않는다는 규칙 때문이다(고침 1).
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from app.outreach import redact
from app.outreach.voice.numbers import DEFAULT_LIVE_MODEL

log = logging.getLogger(__name__)

LIVE_ACTION = "bidiGenerateContent"
FALLBACK = (DEFAULT_LIVE_MODEL, "gemini-3.8-live-extended-thinking")  # 설치된 음성 SDK 가 아는 3.8 Live 모델
TIMEOUT_S = 8
PAGE_SIZE = 200  # 한 번의 요청으로 읽는 줄 수(첫 쪽만)
MAX_MODELS = 30  # 돌려주는 Live 모델 수
_NAME = re.compile(r"[A-Za-z0-9._\-]{1,80}")  # 설정 길이 받는 모델 이름 꼴과 같다

NO_KEY = "음성 모델 키(구글)가 저장돼 있지 않아 기본 목록을 보여 줍니다. 키를 저장하면 그 키로 쓸 수 있는 모델을 읽어 옵니다."
KEY_REFUSED = ("구글이 이 키로 Gemini API 를 쓰지 못하게 합니다(권한 없음). Google AI Studio 에서 만든 Gemini API 키를 넣거나, "
               "이 키의 프로젝트에서 Generative Language API 를 켜 주세요.")
TIMEOUT = "구글이 시간 안에 답하지 않아 기본 목록을 보여 줍니다."
FAILED = "구글에서 모델 목록을 읽지 못해 기본 목록을 보여 줍니다."
NO_CLIENT = "구글 연결 묶음(google-genai)이 서버에 없어 기본 목록을 보여 줍니다."
NO_LIVE = "이 키의 모델 목록에 실시간 음성(Live) 모델이 보이지 않아 기본 목록을 보여 줍니다."


@dataclass(frozen=True)
class LiveModels:
    models: tuple[str, ...]  # 화면에 보일 목록(기본 모델 맨 앞, MAX_MODELS 까지)
    fallback: bool  # 구글에서 읽은 목록이 아니라 고정 목록인가(이때 진단은 모델을 막지 않는다)
    reason: str | None  # fallback 의 까닭(쉬운 한국어). 읽은 목록이면 None
    available: frozenset[str] = frozenset()  # 읽은 Live 모델 전부(자르지 않음) — 진단 전 확인은 이것과 견준다
    refused: bool = False  # 구글이 이 키를 거절했다(400·401·403) — 「못 읽음」이 아니라 분명한 실패. 목록은 비어 있다(고침 2)


def _fallback(reason: str, word: str) -> LiveModels:
    log.info("음성 모델 목록: 기본 목록을 씀(%s)", word)
    return LiveModels(models=FALLBACK, fallback=True, reason=reason)


def google_client(key: str, timeout_s: float) -> object:
    """구글 클라이언트 하나(시험이 바꿔 끼우는 자리). 시간 제한은 밀리초, 다시 시도는 하지 않는다."""
    from google import genai
    from google.genai import types

    options = types.HttpOptions(timeout=int(timeout_s * 1000), retry_options=types.HttpRetryOptions(attempts=1))
    return genai.Client(api_key=key, http_options=options)


def _status(error: BaseException) -> int | None:
    code = getattr(error, "code", None)
    return code if type(code) is int else None


def _names(page: object) -> list[str]:
    """첫 쪽에서 Live 를 받는 모델 이름만(「models/」 를 뗀 꼴, 자르지 않음). 기본 모델을 맨 앞으로."""
    found: list[str] = []
    for item in list(page or [])[:PAGE_SIZE]:
        actions = getattr(item, "supported_actions", None) or []
        raw = getattr(item, "name", None)
        name = raw.removeprefix("models/") if isinstance(raw, str) else ""
        if LIVE_ACTION in actions and _NAME.fullmatch(name) and name not in found:
            found.append(name)
    found.sort(key=lambda n: n != DEFAULT_LIVE_MODEL)
    return found


def list_live_models(key: str | None, client: Callable[[str, float], object] | None = None) -> LiveModels:
    """이 키로 쓸 수 있는 Live 모델. 키가 없거나 무엇이 잘못되면 고정 목록과 까닭(던지지 않는다)."""
    if not key:
        return _fallback(NO_KEY, "no_key")
    redact.add_secrets(key)
    try:
        api = (client or google_client)(key, TIMEOUT_S)
        page = api.models.list(config={"page_size": PAGE_SIZE}).page  # 요청 한 번 — 다음 쪽은 읽지 않는다
        names = _names(page)
    except ImportError:
        return _fallback(NO_CLIENT, "no_client")
    except Exception as e:  # noqa: BLE001 — 글은 읽지 않는다(키가 들 수 있다)
        if _status(e) in (400, 401, 403):  # 키에 Gemini API 권한이 없다(11-24 실제: 403 PERMISSION_DENIED) — 걸어 봐야 끊긴다
            log.info("음성 모델 목록: 구글이 키를 거절함")
            return LiveModels(models=(), fallback=True, reason=KEY_REFUSED, refused=True)
        if isinstance(e, TimeoutError) or "timeout" in type(e).__name__.lower():
            return _fallback(TIMEOUT, "timeout")
        return _fallback(FAILED, type(e).__name__)
    if not names:
        return _fallback(NO_LIVE, "no_live")
    return LiveModels(models=tuple(names[:MAX_MODELS]), fallback=False, reason=None, available=frozenset(names))
