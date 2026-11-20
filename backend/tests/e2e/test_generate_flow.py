"""서버 끝에서 끝까지: 대화로 일정을 만들고, 조건을 바꾸고, 되돌린다(가짜 Liner = ScriptedLlm).

로그인 → 대화 "5층 사무동 공정표 만들어 줘…" → 질문지 → 답·제출 → 생성(3회차 통과) → 승인 건 → 승인
→ 버전 1(처음 계획) → 조건 미리 보기(크레인 2대) → 확정 → 승인 → 버전 2 → 버전 1로 되돌리기 → 버전 3.

생성 대본: 기초 철근 배근과 기초 거푸집이 나란히(둘 다 타워크레인) → 1층 골조 → 준공. 크레인 1대면
자원 맞춤이 하나를 미뤄 준공 2027-04-16, 2대면 둘이 함께 가서 2027-04-05 다(날짜는 코드가 계산한다).
"""

import json

import pytest

import app.tools.generate as generate_pkg
from app.agent import loop
from app.llm.client import LlmClient
from app.tools.registry import to_llm_name
from tests.gen_doubles import START_FACT, WBS_OK, act, input_condition, sched
from tests.gen_doubles import reply as json_reply
from tests.llm_doubles import add_connection
from tests.loop_doubles import ScriptedLlm, calls, reply

FINISH_V1 = "2027-04-16"  # 크레인 1대
FINISH_CRANE2 = "2027-04-05"  # 크레인 2대
CRANE_ID = "in.resource_cap.tower_crane"
PROMPT = "5층 사무동 공정표 만들어 줘. 착공은 2027년 3월 1일, 준공은 4월 16일까지. 타워크레인은 1대야."

FORM = act("A1015", "기초 거푸집", "1.1.1", 10, ["A1000"])


def _draft(frame_od: int) -> dict:
    return sched(frame_od, frame_preds=("A1010", "A1015"), extra=[FORM])


QUESTIONS = [
    {"id": "structure", "group": "범위", "question": "건물의 구조 형식은 무엇인가요?", "why": "골조 기간이 달라집니다.",
     "options": [{"value": "rc", "label": "철근콘크리트", "hint": None, "recommended": True},
                 {"value": "steel", "label": "철골", "hint": None, "recommended": False}],
     "allow_free": True, "assumption": "철근콘크리트로 가정합니다."},
    {"id": "basement", "group": "범위", "question": "지하층이 있나요?", "why": "터파기 기간이 달라집니다.",
     "options": [{"value": "0", "label": "없음", "hint": None, "recommended": True},
                 {"value": "1", "label": "지하 1층", "hint": None, "recommended": False}],
     "allow_free": False, "assumption": "지하층이 없다고 가정합니다."},
    {"id": "work_week", "group": "달력", "question": "주 며칠 일하나요?", "why": "작업 달력을 정합니다.",
     "options": [{"value": "6", "label": "주 6일", "hint": "건설 현장 기본", "recommended": True},
                 {"value": "5", "label": "주 5일", "hint": None, "recommended": False}],
     "allow_free": False, "assumption": "주 6일로 가정합니다."},
]
ASK = {"purpose": "generate", "title": "5층 사무동 일정 질문지", "domain": "construction", "level": "L3",
       "questions": QUESTIONS, "prefilled": [{"label": "착공일", "value": "2027-03-01", "source": "프롬프트"}]}
RUN = {
    "domain": "construction", "level": "L3", "request": PROMPT, "facts": [START_FACT],
    "conditions": [
        input_condition("in.finish_by", "finish_by", {"date": FINISH_V1}, f"준공 {FINISH_V1}까지").to_dict(),
        input_condition(CRANE_ID, "resource_cap", {"resource_id": "tower_crane", "capacity": 1}, "타워크레인 1대").to_dict(),
    ],
    "assumptions": [],
}


@pytest.fixture
def liner(session, monkeypatch) -> ScriptedLlm:
    """대화 루프와 생성 도구가 같은 대본 가짜를 쓴다(기본 연결 하나)."""
    add_connection(session)
    llm = ScriptedLlm()
    monkeypatch.setattr(loop, "default_llm", lambda s: LlmClient(s, transport=llm.transport))
    monkeypatch.setattr(generate_pkg, "client_for", lambda ctx: LlmClient(ctx.session, transport=llm.transport))
    return llm


def _events(body: str) -> list[tuple[str, dict]]:
    """SSE 본문 → [(event, data)]. ping 주석은 건너뛴다."""
    out = []
    for block in body.strip().split("\n\n"):
        if block.startswith(":"):
            continue
        event, data = block.split("\n")
        out.append((event.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def _send(client, headers, chat_id, **body) -> list[tuple[str, dict]]:
    r = client.post(f"/api/chat/sessions/{chat_id}/messages", json={"ui": {}, **body}, headers=headers)
    assert r.status_code == 200, r.text
    events = _events(r.text)
    assert events[-1][0] == "done" and not [e for e in events if e[0] == "error"], events
    return events


def _ok(r, status: int = 200) -> dict:
    assert r.status_code == status, r.text
    return r.json()


def _login(client) -> dict[str, str]:
    token = _ok(client.post("/api/auth/login", json={"login_id": "admin", "password": "test-pass"}))["token"]
    return {"Authorization": f"Bearer {token}"}


def _ask_and_answer(client, h, liner) -> int:
    """대화 → 질문지 → 답·제출 → 대화 이어 가기(생성·승인 건). 승인 건 id 를 준다."""
    chat_id = _ok(client.post("/api/chat/sessions", json={}, headers=h))["id"]
    liner.push(calls("ask.questionnaire", ASK), reply("질문지를 열었습니다. 답을 채워 제출해 주세요."))
    events = _send(client, h, chat_id, text=PROMPT)
    qid = next(data["id"] for name, data in events if name == "questionnaire")
    for question_id, value in (("structure", "rc"), ("work_week", "6")):  # 지하층은 비워 가정으로
        _ok(client.patch(f"/api/questionnaires/{qid}/answers", json={"question_id": question_id, "value": value}, headers=h))
    submitted = _ok(client.post(f"/api/questionnaires/{qid}/submit", headers=h))
    assert [a["assumption"] for a in submitted["assumed"]] == ["지하층이 없다고 가정합니다."]

    liner.push(
        calls("generate.run", RUN),
        json_reply(WBS_OK), json_reply(_draft(23)), json_reply(_draft(21)), json_reply(_draft(20)),
        calls("out.submit_change", {"title": "5층 사무동 신축 일정 저장", "draft_id": 1}, call_id="call_2"),
        reply("승인함에 올렸습니다."),
    )
    events = _send(client, h, chat_id, questionnaire_id=qid)
    card = next(d for name, d in events if name == "card" and d.get("kind") == "generation_result")
    assert (card["ok"], card["draft_id"], card["finish"]) == (True, 1, FINISH_V1)
    run_out = _tool_result(liner, "generate.run")
    assert [r["violations"] for r in run_out["rounds"]] == [1, 1, 0]  # 3회차 통과
    return next(d["id"] for name, d in events if name == "approval")


def _tool_result(liner: ScriptedLlm, name: str) -> dict:
    """루프가 LLM 에 돌려준 도구 결과(그 도구를 부른 호출 id 의 tool 메시지)."""
    wire = to_llm_name(name)
    for body in liner.bodies:
        waiting: set[str] = set()  # 호출 id 는 턴마다 겹칠 수 있어 차례대로 본다
        for m in body["messages"]:
            if m["role"] == "tool" and m.get("tool_call_id") in waiting:
                return json.loads(m["content"])
            if m["role"] == "assistant":
                waiting = {c["id"] for c in m.get("tool_calls") or [] if c["function"]["name"] == wire}
    raise AssertionError(f"{name} 결과를 받은 요청이 없습니다")


def _approve(client, h, approval_id: int) -> dict:
    return _ok(client.post(f"/api/approvals/{approval_id}/decide", json={"decision": "approve", "note": ""}, headers=h))


def _crane(capacity: int, base_version: int) -> dict:
    return {"base_version": base_version, "changes": [{"id": CRANE_ID, "params": {"capacity": capacity}}]}


def test_generate_then_change_conditions_then_restore(client, liner):
    h = _login(client)
    first = _ask_and_answer(client, h, liner)
    assert _approve(client, h, first)["status"] == "approved"
    sid = _ok(client.get("/api/schedules", headers=h))[0]["id"]
    view_v1 = _ok(client.get(f"/api/schedules/{sid}", headers=h))
    assert (view_v1["version"], view_v1["finish"]) == (1, FINISH_V1)
    assert [(v["n"], v["is_plan"]) for v in _ok(client.get(f"/api/schedules/{sid}/versions", headers=h))] == [(1, True)]

    preview = _ok(client.post(f"/api/schedules/{sid}/conditions/preview", json=_crane(2, 1), headers=h))
    assert (preview["before"]["finish"], preview["after"]["finish"]) == (FINISH_V1, FINISH_CRANE2)
    assert preview["moved"] and preview["view"]["finish"] == FINISH_CRANE2
    committed = _ok(client.post(f"/api/schedules/{sid}/conditions/commit", json=_crane(2, 1), headers=h))
    assert committed["applied"] is False  # 조건이 바뀌었으니 승인함에서 기다린다
    _approve(client, h, committed["approval_id"])
    view_v2 = _ok(client.get(f"/api/schedules/{sid}", headers=h))
    assert (view_v2["version"], view_v2["finish"]) == (2, FINISH_CRANE2)

    view_after_restore = _ok(client.post(f"/api/schedules/{sid}/versions/1/restore", json={"base_version": 2}, headers=h))
    versions = _ok(client.get(f"/api/schedules/{sid}/versions", headers=h))
    assert view_after_restore["version"] == 3
    assert [v["n"] for v in versions] == [3, 2, 1] and versions[-1]["is_plan"] is True
    assert [v["is_plan"] for v in versions] == [False, False, True]  # 「처음 계획」 표시는 버전 1 에만
    assert view_after_restore["finish"] == view_v1["finish"]
