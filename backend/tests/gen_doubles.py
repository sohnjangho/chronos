"""일정 생성 시험용 자료: 가짜 LLM 답(WBS·스케줄 초안)과 조건.

일정 모양: 착공(마일스톤) → 기초 철근 배근(10일) → 1층 골조(frame_od 일) → 준공(마일스톤).
분야 기본 달력(주 6일·2027 공휴일), 착공일 2027-03-01(삼일절)이면 첫 작업은 03-02 에 시작하고,
frame_od=20 이면 준공이 2027-04-05 다. 21 이면 04-06(하루 늦음), 23 이면 04-08(사흘 늦음).
"""

import json

from app.harness.conditions import Condition
from tests.llm_doubles import FakeLiner, chat_body

FINISH = "2027-04-05"

WBS_OK = {
    "wbs": [
        {"code": "1", "name": "사무동", "parent": None},
        {"code": "1.1", "name": "기초", "parent": "1"},
        {"code": "1.1.1", "name": "기초 공사", "parent": "1.1"},
        {"code": "1.2", "name": "골조", "parent": "1"},
        {"code": "1.2.1", "name": "지상 골조", "parent": "1.2"},
    ]
}


def act(i: str, name: str, wbs: str, od: int, preds=(), *, kind: str = "task", tags=(), **extra) -> dict:
    """LLM 이 내는 액티비티 한 줄. preds 는 FS lag 0 선행 id."""
    return {
        "id": i,
        "name": name,
        "kind": kind,
        "wbs": wbs,
        "od": od,
        "tags": list(tags),
        "predecessors": [{"pred": p, "type": "FS", "lag": 0} for p in preds],
        **extra,
    }


def sched(frame_od: int = 20, *, frame_preds=("A1010",), extra=()) -> dict:
    return {
        "activities": [
            act("A1000", "착공", "1.1.1", 0, kind="start_ms"),
            act("A1010", "기초 철근 배근", "1.1.1", 10, ["A1000"]),
            *extra,
            act("A1020", "1층 골조", "1.2.1", frame_od, frame_preds),
            act("A1030", "준공", "1.2.1", 0, ["A1020"], kind="finish_ms"),
        ]
    }


SCHED_OK = sched(20)
SCHED_LATE_BY_1 = sched(21)
SCHED_LATE_BY_3 = sched(23)
# 기초 거푸집이 철근 배근과 나란히 → 타워크레인을 같은 날 둘이 쓴다(맞춤이 하나를 미룬다)
SCHED_PARALLEL_CRANE = sched(
    20,
    frame_preds=("A1010", "A1015"),
    extra=[act("A1015", "기초 거푸집", "1.1.1", 10, ["A1000"])],
)
SCHED_CYCLE = {
    "activities": [
        act("A1000", "착공", "1.1.1", 0, kind="start_ms"),
        act("A1010", "기초 철근 배근", "1.1.1", 10, ["A1000", "A1020"]),
        act("A1020", "1층 골조", "1.2.1", 20, ["A1010"]),
        act("A1030", "준공", "1.2.1", 0, ["A1020"], kind="finish_ms"),
    ]
}
SCHED_BAD_WBS = sched(20, extra=[act("A1015", "기초 거푸집", "9.9", 10, ["A1000"])])
# LLM 이 날짜를 지어내 보낸 초안(코드는 버려야 한다)
SCHED_OK_WITH_FAKE_DATES = {
    "activities": [
        {**a, "es": "2027-01-04", "ef": "2027-01-05", "start": "2027-01-04", "finish": "2027-01-05"}
        for a in SCHED_OK["activities"]
    ],
    "start": "2027-01-04",
    "finish": "2027-01-30",
}


def input_condition(cid: str, kind: str, params: dict, text: str, source: str = "프롬프트") -> Condition:
    return Condition(cid, "input", kind, params, text, source)


FINISH_BY = input_condition("in.finish_by", "finish_by", {"date": FINISH}, f"준공 {FINISH}까지")
CRANE_CAP = input_condition(
    "in.resource_cap.tower_crane", "resource_cap", {"resource_id": "tower_crane", "capacity": 1}, "타워크레인 1대", "질문지"
)
START_FACT = {"label": "착공일", "value": "2027-03-01", "source": "프롬프트"}


def reply(item: dict | str) -> dict:
    """가짜 Liner 응답 본문. dict 는 JSON 글로, 글은 그대로 답한다."""
    return chat_body(item if isinstance(item, str) else json.dumps(item, ensure_ascii=False))


def script(liner: FakeLiner, *items: dict | str | Exception) -> None:
    """대본을 차례로 쌓는다. 예외는 그대로(통신 실패)."""
    liner.push(*(item if isinstance(item, Exception) else reply(item) for item in items))


def messages(liner: FakeLiner, n: int) -> list[dict]:
    """n 번째(0부터) 요청의 messages."""
    return liner.bodies[n]["messages"]


def user_text(liner: FakeLiner, n: int) -> str:
    return "\n".join(m["content"] for m in messages(liner, n) if m["role"] == "user")


def system_text(liner: FakeLiner, n: int) -> str:
    return "\n".join(m["content"] for m in messages(liner, n) if m["role"] == "system")
