"""대화마다 도는 턴을 하나로 묶고, 멈춤 요청을 전한다(프로세스 메모리에만 둔다).

대화 API 는 턴을 시작하기 전에 claim 하고(이미 돌고 있으면 TurnRunning), 턴이 끝나면 release 한다.
POST …/stop 은 request_stop 으로 표시만 하고, 에이전트 루프가 단계 사이에서 stop_requested 를 본다
(생성 도구는 ToolContext.stop_requested 로 LLM 을 부르기 전에 본다).
서버를 다시 띄우면 모두 풀린다.

서버 작업자(uvicorn worker)가 하나라고 본다. 작업자가 여럿이면 이 표가 작업자마다 따로 있어서,
409(턴이 도는 중)와 멈춤이 같은 작업자에 온 요청끼리만 맞는다.
"""

from dataclasses import dataclass


class TurnRunning(Exception):
    """그 대화에서 이미 턴이 돌고 있다."""


@dataclass(eq=False)
class Claim:
    chat_session_id: int
    stop: bool = False


_running: dict[int, Claim] = {}


def claim(chat_session_id: int) -> Claim:
    """턴을 맡는다. 이미 돌고 있으면 TurnRunning."""
    if chat_session_id in _running:
        raise TurnRunning(chat_session_id)
    _running[chat_session_id] = held = Claim(chat_session_id)
    return held


def release(chat_session_id: int, held: Claim) -> None:
    """맡은 턴을 놓는다. 그 사이 다른 턴이 맡았으면(held 가 다르면) 건드리지 않는다. 여러 번 불러도 된다."""
    if _running.get(chat_session_id) is held:
        del _running[chat_session_id]


def is_running(chat_session_id: int) -> bool:
    return chat_session_id in _running


def request_stop(chat_session_id: int) -> bool:
    """돌고 있는 턴에 멈춤을 표시한다. 돌고 있는 턴이 없으면 False."""
    held = _running.get(chat_session_id)
    if held is None:
        return False
    held.stop = True
    return True


def stop_requested(chat_session_id: int) -> bool:
    held = _running.get(chat_session_id)
    return held is not None and held.stop


def active_turns() -> list[dict]:
    """현재 실행 중인 턴 목록(chat_session_id 오름차순)."""
    return [
        {"chat_session_id": cid, "stop_requested": held.stop}
        for cid, held in sorted(_running.items())
    ]
