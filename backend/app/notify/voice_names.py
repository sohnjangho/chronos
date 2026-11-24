"""음성 진단 P9: 설정한 음성 이름을 공급자가 받는지 — 전화 없이(계획 4 Task 99 고침 1). diagnostics_voice._Run.voices 가 부른다.

음성 SDK 에는 음성 목록이 없어(P9 not_supported) 음성 이름은 사람이 손으로 넣는다. 없는 이름이면 그 칸을 쓰는 전화는 상대가 받은 뒤
끊기므로, 설정한 이름마다(같은 이름은 한 번, 많아야 MAX_VOICES 개) 실시간 세션을 그 음성으로 열었다(prewarm — 첫 인사 없음) 닫는다
(stop). 구글은 setup 을 거절하면 여는 데서 예외가 나고, OpenAI 는 session.update 를 거절해도 오류 사건만 보내 SDK 가 「OpenAI error:」
줄 하나를 남긴다(그 줄은 진단이 로그 거르개에서 센다 — `run.model_errors`). 결과 줄에는 음성 이름을 싣지 않고 칸 이름표만 싣는다.
여는 데 쓰는 키·모델은 진단과 같고, 플랫폼(전화)은 건드리지 않는다. 실제 공급자로는 확인하지 못했다(가짜 SDK 시험만).
"""

from app.notify.voice_sdk_logs import _http_status
from app.outreach.voice.numbers import GOOGLE_LIVE_API_VERSION

VOICE_OPEN_S, VOICE_SETTLE_S, VOICE_STOP_S = 8, 2, 3  # 열기 · (OpenAI) 오류 줄을 기다림 · 닫기
MAX_VOICES = 8
BUDGET_S = MAX_VOICES * (VOICE_OPEN_S + VOICE_SETTLE_S + VOICE_STOP_S + 1)  # 설정 API 의 시간 상한에 더한다
PROMPT = "음성 확인용 연결입니다. 아무 말도 하지 않습니다."
REJECTED = "이 음성 이름을 공급자가 받지 않았습니다"
REJECTED_TAIL = " — 이 칸을 쓰는 전화는 상대가 받은 뒤 끊깁니다. 칸을 고친 뒤 다시 진단해 주세요."
UNCONFIRMED = "시간 안에 확인하지 못한 음성이 있습니다"
MODEL_FAILED = "AI 음성 모델에 연결하지 못해 음성을 확인하지 못했습니다 — 음성 모델 키·모델을 확인해 주세요."
KEY_STATUSES = frozenset({401, 403, 404})  # 키·모델 문제 — 음성 탓으로 돌리지 않는다


def _named(voices: object) -> dict[str, list[str]]:
    """{음성 이름: [칸 이름표…]} — 설정의 칸 차례, 같은 이름은 한 묶음."""
    found: dict[str, list[str]] = {}
    for item in voices if isinstance(voices, tuple | list) else ():
        if isinstance(item, tuple | list) and len(item) == 2 and all(isinstance(x, str) and x for x in item):
            found.setdefault(item[1], []).append(item[0])
    return found


async def _try(run: object, session_class: object, name: str) -> str:
    """음성 하나: "ok" · "rejected" · "model"(키·모델 문제) · "timeout". 던지지 않는다(취소만)."""
    voice = run.voice
    kw = {"api_key": voice.key, "system_prompt": PROMPT, "language": "ko", "voice": name, "greeting": False}
    if voice.model:
        kw["model"] = voice.model
    if voice.provider == "google":
        kw["api_version"] = GOOGLE_LIVE_API_VERSION
    session = session_class(**kw)
    before = run.model_errors
    try:
        await run.bounded(session.prewarm(), VOICE_OPEN_S)
        until = run.clock() + (VOICE_SETTLE_S if voice.provider == "openai" else 0)
        while run.model_errors == before and run.clock() < until:
            await run.sleep(0.1)
        return "rejected" if run.model_errors > before else "ok"
    except TimeoutError:
        return "timeout"
    except Exception as e:  # noqa: BLE001 — 예외 글은 버린다(계정·키가 들 수 있다)
        return "model" if _http_status(e) in KEY_STATUSES else "rejected"
    finally:
        try:
            await run.bounded(session.stop(), VOICE_STOP_S)
        except Exception:  # noqa: BLE001, S110 — 닫지 못해도 결과는 그대로
            pass


async def check(run: object, session_class: object) -> None:
    """P9 줄을 run 에 남긴다. 세션을 만들 수 없으면(묶음 없음·다른 서명) 그 까닭으로."""
    named = _named(run.voice.voices)
    picked = list(named)[:MAX_VOICES]
    notes = [f"음성이 {len(named)}개라 앞의 {MAX_VOICES}개만 확인했습니다."] if len(named) > MAX_VOICES else []
    results: dict[str, str] = {}
    try:
        for name in picked:
            results[name] = await _try(run, session_class, name)
    except ImportError:
        return run.put(9, "sdk_extra_missing", "고른 음성 모델에 필요한 묶음이 설치돼 있지 않아 음성을 확인하지 못했습니다.")
    except (AttributeError, TypeError) as e:
        return run.put(9, "sdk_signature", "설치된 음성 SDK 가 확인해 둔 판과 달라 음성을 확인하지 못했습니다.",
                       notes=[f"예외: {type(e).__name__}"])
    labels = {kind: " · ".join(label for name, what in results.items() if what == kind for label in named[name])
              for kind in ("rejected", "model", "timeout")}
    data = {"checked": len(picked)}
    if labels["rejected"]:
        count = sum(what == "rejected" for what in results.values())
        return run.put(9, "voice_rejected", f"{REJECTED}: {labels['rejected']}{REJECTED_TAIL}", notes=notes,
                       data={**data, "rejected": count})
    if labels["model"]:
        return run.put(9, "model_connect_failed", MODEL_FAILED, notes=notes, data=data)
    if labels["timeout"]:
        return run.put(9, "voice_unconfirmed", f"{UNCONFIRMED}: {labels['timeout']}. 잠시 뒤 다시 진단해 주세요.",
                       notes=notes, data=data)
    return run.put(9, "ok", f"설정한 음성 {len(picked)}개를 공급자가 받았습니다 — 전화는 걸지 않았습니다.", ok=True,
                   notes=notes, data=data)
