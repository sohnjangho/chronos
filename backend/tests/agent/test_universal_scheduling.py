"""범용 일정 생성·동적 도메인 합성·2단계 적응형 질문지 가드레일 시험."""

import json
from datetime import date

import httpx
import pytest

from app.agent import context
from app.agent.domain_synth import synthesize_pack
from app.agent.generation import generate
from app.agent.loop import run_turn
from app.domains.loader import UnknownDomain, resolve_pack
from app.harness.conditions import Condition
from app.llm.client import MAX_TOKENS, LlmClient
from app.store import chats
from app.store.schedules import create_schedule
from app.store.tables import User
from app.tools import registry
from app.tools.context import ToolContext
from tests.gen_doubles import act, script
from tests.llm_doubles import FakeLiner, add_connection, chat_body
from tests.loop_doubles import ScriptedLlm, calls, reply
from tests.schedules import sample

NO_UI = context.UiContext(None, None, None)


def _profile_reply(domain_name: str, res_id: str, res_name: str) -> dict:
    return {
        "domain_name": domain_name,
        "days_per_week": 5,
        "deadline_label": "목표 완료일",
        "start_term": "시작",
        "activity_term": "작업",
        "resource_term": "자원",
        "rules": ["선행 검토 후 본 작업 착수"],
        "key_resources": [{"id": res_id, "name": res_name, "unit": "명"}],
        "wbs_phases": [
            {"code": "1", "name": "기획·조사", "subphases": [{"code": "1.1", "name": "기초 분석"}]},
            {"code": "2", "name": "실행·검증", "subphases": [{"code": "2.1", "name": "핵심 수행"}]},
        ],
        "assumption_defaults": [{"label": "예비 버퍼", "value": "10%", "note": "완료 전 버퍼"}],
    }


def test_resolve_pack_supports_any_valid_domain_and_rejects_unsafe_ids():
    for dom, expected in [("rnd", "R&D 연구개발"), ("permitting", "인허가"), ("procurement", "자재 공급"), ("general", "일반")]:
        pack = resolve_pack(dom)
        assert pack.id == dom and pack.name == expected
        assert pack.display.deadline_label == "완료 기한"
    custom = resolve_pack("event_expo")
    assert custom.id == "event_expo"
    for bad in ("", "   ", "../etc", "a/b", "a\\b"):
        with pytest.raises(UnknownDomain):
            resolve_pack(bad)


async def test_synthesize_pack_builds_custom_profile_and_falls_back_on_error(session):
    add_connection(session)
    liner = FakeLiner()
    script(liner, _profile_reply("R&D 연구개발", "lead_researcher", "책임 연구원"))
    llm = LlmClient(session, transport=liner.transport)
    cap = Condition("in.resource_cap.extra_lab", "input", "resource_cap", {"resource_id": "extra_lab", "capacity": 1}, "실험실 1실", "질문지")

    pack = await synthesize_pack(llm, "rnd", "배터리 R&D 일정", conditions=[cap])
    assert pack.name == "R&D 연구개발"
    assert [r.id for r in pack.key_resources] == ["lead_researcher", "extra_lab"]
    assert pack.rules_raw[0]["source"] == "분야 규칙"

    # LLM 오류 시에도 범용 기본 팩으로 안전하게 폴백
    liner_err = FakeLiner()
    script(liner_err, httpx.ReadTimeout("timeout"))
    llm_err = LlmClient(session, transport=liner_err.transport)
    fallback = await synthesize_pack(llm_err, "permitting", "공장 인허가 일정")
    assert fallback.id == "permitting" and fallback.name == "인허가"


async def test_generate_universal_domain_supports_dynamic_resources_and_custom_tags(session):
    add_connection(session)
    liner = FakeLiner()
    wbs = {
        "wbs": [
            {"code": "1", "name": "조달 준비", "parent": None},
            {"code": "1.1", "name": "발주·제작", "parent": "1"},
            {"code": "2", "name": "검수·입고", "parent": None},
            {"code": "2.1", "name": "현장 검수", "parent": "2"},
        ]
    }
    draft = {
        "resources": [
            {"id": "buyer_team", "name": "조달 담당자", "unit": "명", "capacity": 1},
            {"id": "qa_inspector", "name": "품질 검사원", "unit": "명", "capacity": 2},
        ],
        "activities": [
            act("A1000", "발주 개시", "1.1", 0, kind="start_ms", resources=[]),
            act("A1010", "특수 장비 발주·제작", "1.1", 10, ["A1000"], tags=["조달"], resources=["buyer_team"]),
            act("A1020", "예비품 선적 조율", "1.1", 8, ["A1000"], tags=["물류"], resources=["buyer_team"]),
            act("A1030", "현장 QA 검수", "2.1", 5, ["A1010", "A1020"], tags=["품질"], resources=["qa_inspector"]),
            act("A1040", "최종 입고 완료", "2.1", 0, ["A1030"], kind="finish_ms", resources=[]),
        ],
    }
    script(liner, _profile_reply("자재 공급", "buyer_team", "조달 담당자"), wbs, draft)
    llm = LlmClient(session, transport=liner.transport)
    admin = session.query(User).filter_by(login_id="admin").one()
    chat = chats.create_chat(session, user_id=admin.id)
    ctx = ToolContext(session=session, user=admin, schedule_id=None, chat_session_id=chat.id, emit=lambda _e: None)

    cap = Condition("in.resource_cap.buyer_team", "input", "resource_cap", {"resource_id": "buyer_team", "capacity": 1}, "조달 담당자 1명", "프롬프트")
    r = await generate(
        ctx,
        llm,
        domain="procurement",
        level="L3",
        request="해외 특수 장비 조달 일정",
        facts=[{"label": "발주일", "value": "2027-05-03", "source": "프롬프트"}],
        inputs=[cap],
    )
    assert r.ok, r.reason
    assert r.schedule.start == date(2027, 5, 3)
    res_ids = {x.id: x.capacity for x in r.schedule.resources}
    assert res_ids["buyer_team"] == 1 and res_ids["qa_inspector"] == 2
    a1010 = next(a for a in r.schedule.activities if a.id == "A1010")
    a1020 = next(a for a in r.schedule.activities if a.id == "A1020")
    assert a1010.tags == ("조달",) and a1010.resources == ("buyer_team",)
    assert a1020.resources == ("buyer_team",)
    # 용량 1 자원을 공유하므로 A1010 과 A1020 은 평준화로 순차/미뤄져 날짜가 겹치지 않음
    assert r.report.violations == []


async def test_loop_blocks_duplicate_questionnaire_in_single_turn(session):
    registry.load_all()
    add_connection(session)
    admin = session.query(User).filter_by(login_id="admin").one()
    chat_id = chats.create_chat(session, user_id=admin.id).id

    q_card = {
        "purpose": "generate",
        "title": "분야 확인",
        "domain": None,
        "level": None,
        "round": 1,
        "questions": [
            {
                "id": "topic",
                "group": "주제",
                "question": "어떤 일정인가요?",
                "why": "주제 파악",
                "options": [{"value": "rnd", "label": "R&D", "recommended": True}],
                "allow_free": True,
                "assumption": "R&D로 진행",
            }
        ],
    }
    second_q = {
        **q_card,
        "title": "추가 질문지",
        "domain": "construction",
        "questions": [
            {**q_card["questions"][0], "id": "q1"},
            {**q_card["questions"][0], "id": "q2"},
            {**q_card["questions"][0], "id": "q3"},
        ],
    }
    llm = ScriptedLlm(
        [
            calls("ask.questionnaire", q_card),
            calls("ask.questionnaire", second_q),
            reply("어떤 분야의 일정인지 카드에서 알려 주세요."),
        ]
    )
    events = [
        e async for e in run_turn(session, admin, chat_id, "새 스케줄 만들어줘", NO_UI, llm=LlmClient(session, transport=llm.transport))
    ]
    tool_ends = [e.data for e in events if e.type == "tool_end"]
    assert len(tool_ends) == 2
    assert tool_ends[0]["ok"] is True
    assert tool_ends[1]["ok"] is False and "이미 질문" in tool_ends[1]["error"]


def test_build_context_avoids_construction_bias_for_blank_or_universal_requests(session, monkeypatch):
    monkeypatch.setattr(context, "today", lambda: date(2026, 11, 21))
    admin = session.query(User).filter_by(login_id="admin").one()
    sid_construction = create_schedule(
        session,
        name="기존 사무동 건설",
        domain="construction",
        level="L3",
        schedule=sample(),
        conditions=[],
        by_kind="agent",
        by_name="에이전트",
        note="기준",
    )

    prompts = (
        "새로운 스케줄 만들어줘",
        "R&D 연구개발 일정 만들어줘",
        "건축·환경·소방 통합 인허가 일정 만들어줘",
        "해외 자재공급일정 만들어줘",
    )
    for ui in (NO_UI, context.UiContext("chat", sid_construction, None)):
        for msg in prompts:
            cid = chats.create_chat(session, user_id=admin.id).id
            chats.add_message(session, cid, "user", {"kind": "text", "text": msg})
            session.commit()
            sys_prompt = context.build_context(session, admin, cid, ui)[0]["content"]
            assert "타워크레인" not in sys_prompt and "대표 WBS 틀:\n- 1 기초" not in sys_prompt


async def test_generate_rejects_disconnected_zero_relation_draft_and_repairs(session):
    add_connection(session)
    liner = FakeLiner()
    wbs = {
        "wbs": [
            {"code": "1", "name": "단계 1", "parent": None},
            {"code": "1.1", "name": "세부 1", "parent": "1"},
        ]
    }
    disconnected = {
        "resources": [],
        "activities": [
            act("A1", "작업 1", "1.1", 3, []),
            act("A2", "작업 2", "1.1", 4, []),
            act("A3", "작업 3", "1.1", 5, []),
            act("A4", "작업 4", "1.1", 2, []),
        ],
    }
    connected = {
        "resources": [],
        "activities": [
            act("A1000", "시작", "1.1", 0, [], kind="start_ms"),
            act("A1010", "작업 1", "1.1", 3, ["A1000"]),
            act("A1020", "작업 2", "1.1", 4, ["A1010"]),
            act("A1030", "완료", "1.1", 0, ["A1020"], kind="finish_ms"),
        ],
    }
    script(liner, _profile_reply("연구개발", "researcher", "연구원"), wbs, disconnected, connected)
    llm = LlmClient(session, transport=liner.transport)
    admin = session.query(User).filter_by(login_id="admin").one()
    chat = chats.create_chat(session, user_id=admin.id)
    ctx = ToolContext(session=session, user=admin, schedule_id=None, chat_session_id=chat.id, emit=lambda _e: None)

    r = await generate(ctx, llm, domain="rnd", level="L3", request="연구 일정", facts=[{"label": "시작일", "value": "2027-03-02", "source": "프롬프트"}])
    assert r.ok, r.reason
    assert r.rounds[0].violations == -1 and r.rounds[1].violations == 0
    assert len(r.schedule.relations) == 3


async def test_llm_client_max_tokens_override_preserves_defaults(session):
    add_connection(session)
    liner = FakeLiner()
    liner.push(chat_body("기본"), chat_body("상향"))
    llm = LlmClient(session, transport=liner.transport)
    await llm.chat("light", [{"role": "user", "content": "hi"}])
    assert liner.last_body["max_tokens"] == MAX_TOKENS["light"]
    await llm.chat("light", [{"role": "user", "content": "hi"}], max_tokens=6000)
    assert liner.last_body["max_tokens"] == 6000
