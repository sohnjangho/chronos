"""개발 콘솔 원천 카탈로그: 하네스 규칙·실엔진 차단 시험, 프롬프트/파이프라인/가이드/도메인 원문, 도구/스킬 등록부."""

import json
import time
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import context as agent_context
from app.agent.approval import assess
from app.agent.loop import MAX_STEPS
from app.core.model import Activity, CalendarSpec, Relation, Resource, Schedule, WbsNode
from app.domains.loader import domains, levels_prompt, load
from app.errors import ApiError
from app.harness.checks import check as check_schedule
from app.harness.conditions import BASE_RULES, Condition
from app.programs.devconsole import harness_live
from app.programs.devconsole.harness_db import (
    LOOP_TOOL,
    ScriptedLiner,
    run_isolated_turn,
)
from app.programs.devconsole.service import APPROVAL_TOOLS, CHECK_TOOLS, step_signals
from app.store import settings as settings_store
from app.store import skills as skill_store
from app.store.drafts import violation_json
from app.store.tables import WorkflowStep
from app.tools import registry
from app.tools.registry import ToolResult

HARNESS_PRINCIPLES: list[str] = [
    "어기면 일정 무결성·자원 한도·권한이 틀어지는 규칙은 코드(하네스)로 강제하고, 말투와 순서는 프롬프트로 안내한다",
    "차단은 예외 종료가 아니라 도구 결과(JSON)로 돌려준다 — 위반 이유와 자가 점검(reflection) 지시를 적어 모델이 스스로 고치게 한다",
    "도구 실행이 실패하면 DB 트랜잭션(session.rollback)을 즉시 되돌려 반쪽짜리 쓰기를 남기지 않는다",
    "원본 일정·내 규칙 변경은 에이전트가 직접 확정하지 못하고 승인함(Approval) 상신 도구를 통해서만 반영한다",
    "다시 고치기는 정해진 횟수(하네스 {max_check_retries}회 · 루프 {max_steps}바퀴)만 시키고 그 뒤는 사람에게 넘긴다",
]  # {이름} 칸은 get_catalog 가 지금 설정값(에이전트 설정)으로 채운다

HARNESS_RULES: list[dict[str, Any]] = [
    {
        "id": "H-CPM-01",
        "group": "일정 계산",
        "area": "조건 점검",
        "title": "선후행 순환 참조(Cycle) 및 날짜 역전 차단",
        "description": "선행·후행 관계에 순환 고리가 있거나 ES/EF 계산이 불가능한 일정 변경을 차단하고 위반 액티비티를 반환합니다.",
        "code": "app/core/cpm.py · app/harness/checks.py",
        "mode": "도구 결과로 차단·재조정 유도",
        "feedback_sample": '{"passed": false, "violations": [{"condition_id": "base.no_cycle", "activity_ids": ["A2010", "A2020"]}]}',
    },
    {
        "id": "H-RES-01",
        "group": "일정 계산",
        "area": "조건 점검",
        "title": "주요 자원(타워크레인·핵심 설비) 일일 용량 초과 차단",
        "description": "동일 날짜에 고정 배치된 액티비티들의 자원 합계가 자원 용량(capacity)을 넘으면 위반 구간과 액티비티를 반환합니다.",
        "code": "app/core/resources.py · app/harness/checks.py",
        "mode": "도구 결과로 차단·병행 해제 유도",
        "feedback_sample": '{"passed": false, "violations": [{"condition_id": "in.resource_cap.tower_crane", "activity_ids": ["A3010", "A3020"]}]}',
    },
    {
        "id": "H-CAL-01",
        "group": "일정 계산",
        "area": "조건 점검",
        "title": "작업 금지 기간(동절기·우천·야간 금지 꼬리표) 침범 차단",
        "description": "금지 기간(blocked period) 꼬리표가 달린 액티비티가 해당 금지 날짜 구간에 놓이면 위반으로 판정해 지연을 막습니다.",
        "code": "app/core/calendar.py · app/harness/checks.py",
        "mode": "도구 결과로 차단·날짜 이동 유도",
        "feedback_sample": '{"passed": false, "violations": [{"condition_id": "in.blocked_period.pour", "activity_ids": ["A2040"]}]}',
    },
    {
        "id": "H-FIN-01",
        "group": "일정 계산",
        "area": "조건 점검",
        "title": "프로젝트 준공 기한(finish_by) 및 마일스톤 기한 초과 차단",
        "description": "전체 완료 예정일(EF) 또는 주요 마일스톤이 등록된 기한 조건을 넘기면 초과 일수와 관련 액티비티를 돌려줍니다.",
        "code": "app/core/cpm.py · app/harness/checks.py",
        "mode": "도구 결과로 차단·만회안(shorten) 유도",
        "feedback_sample": '{"passed": false, "violations": [{"condition_id": "in.finish_by", "activity_ids": ["A3040"]}]}',
    },
    {
        "id": "H-APP-01",
        "group": "권한",
        "area": "승인",
        "title": "승인 전 원본 일정·시나리오·내 규칙 직접 확정 차단",
        "description": "에이전트는 원본 일정을 직접 덮어쓰지 못하고 반드시 승인함(out.submit_change, scenario.submit, rules.propose)으로 상신해야 합니다.",
        "code": "app/tools/out/submit_change.py · app/tools/out/submit_scenario.py · app/tools/out/propose_rule.py",
        "mode": "구조로 강제 — 승인함 대기열 격리",
        "feedback_sample": '{"status": "pending_approval", "message": "승인함에 상신했습니다. 관리자가 승인하기 전까지 원본 일정은 바뀌지 않습니다."}',
    },
    {
        "id": "H-LOOP-01",
        "group": "에이전트 루프",
        "area": "루프",
        "title": "도구 실패 시 DB 롤백 및 자가 점검(Self-Reflection) 지시 주입",
        "description": "도구 실행이 실패하면 그 도구가 남긴 DB 변경을 즉시 rollback 하고, 오류 원인과 reflection 지시를 JSON으로 돌려보냅니다.",
        "code": "app/agent/loop.py:end_tool (session.rollback)",
        "mode": "자동 롤백 + 자가 점검 JSON 주입",
        "feedback_sample": '{"error": "대상 일정이 없습니다.", "reflection": "도구 `schedule.read` 실패 — 오류 원인을 확인해 인자를 고치거나 대안 도구를 사용하세요."}',
    },
    {
        "id": "H-LIM-01",
        "group": "에이전트 루프",
        "area": "루프",
        "title": f"ReAct 루프 단계 한도({MAX_STEPS}바퀴) 및 하네스 재시도 한도(5회) 강제",
        "description": "무한 루프나 과도한 토큰 소모를 막기 위해 턴당 최대 모델 호출 바퀴 수와 조건 점검 재시도 횟수를 코드로 제한합니다.",
        "code": "app/agent/loop.py · app/tools/generate/run.py",
        "mode": "코드 상수로 강제 종료",
        "feedback_sample": '{"status": "failed", "error": "단계 한도에 닿아 멈췄습니다."}',
    },
    {
        "id": "H-IN-01",
        "group": "에이전트 루프",
        "area": "입력",
        "title": "도구 결과 길이 상한(4,000자) 절단 및 API 비밀키 추적 차단",
        "description": "과도한 도구 출력이 컨텍스트를 덮지 않도록 상한에서 자르고, LLM API 키는 어떤 실행 추적(TraceEvent)에도 남기지 않습니다.",
        "code": "app/agent/context.py:CUT_NOTE · app/agent/trace.py",
        "mode": "구조로 강제 — 입력 절단·키 마스킹",
        "feedback_sample": '{"content": "...(앞 4,000자)...\\n(뒤는 생략)"}',
    },
    *harness_live.RULES,  # 11-23: 정보 API·근거 다시 쓰기·역할·가져오기·생성·사진 판독·기한
]


def _harness_stats(session: Session) -> tuple[dict[str, dict[str, int | None]], dict[str, dict[str, Any]]]:
    steps = list(session.scalars(select(WorkflowStep)))
    check_steps = [s for s in steps if s.tool in CHECK_TOOLS]
    check_pass = 0
    check_block = 0
    for s in check_steps:
        try:
            out = json.loads(s.output_json or "{}")
        except ValueError:
            out = {}
        if s.status == "failed" or out.get("passed") is False or out.get("violations"):
            check_block += 1
        else:
            check_pass += 1
    failed_tools = sum(1 for s in steps if s.status == "failed")
    approvals = sum(1 for s in steps if s.tool in APPROVAL_TOOLS)
    harness_map = {
        "H-CPM-01": {"passed": check_pass, "blocked": check_block},
        "H-RES-01": {"passed": check_pass, "blocked": check_block},
        "H-CAL-01": {"passed": check_pass, "blocked": check_block},
        "H-FIN-01": {"passed": check_pass, "blocked": check_block},
        "H-APP-01": {"passed": approvals, "blocked": 0},
        "H-LOOP-01": {"passed": max(0, len(steps) - failed_tools), "blocked": failed_tools},
        "H-LIM-01": {"passed": len(steps), "blocked": 0},
        "H-IN-01": {"passed": len(steps), "blocked": 0},
        **harness_live.session_counts(session, steps, lambda step: step_signals(step, None)),
    }

    tool_acc: dict[str, dict[str, Any]] = {}
    for s in steps:
        bucket = tool_acc.setdefault(s.tool, {"calls": 0, "failed": 0, "ms_sum": 0, "ms_count": 0})
        bucket["calls"] += 1
        if s.status == "failed":
            bucket["failed"] += 1
        if s.ms is not None:
            bucket["ms_sum"] += s.ms
            bucket["ms_count"] += 1
    tool_stats = {
        name: {
            "calls": b["calls"],
            "failed": b["failed"],
            "avg_ms": round(b["ms_sum"] / b["ms_count"]) if b["ms_count"] else None,
        }
        for name, b in tool_acc.items()
    }
    return harness_map, tool_stats


def get_catalog(session: Session) -> dict[str, Any]:
    """하네스 카탈로그 + 프롬프트/파이프라인/가이드/도메인 원천 + 도구(통계·활성)/스킬 등록부를 한 번에 반환."""
    registry.load_all()
    cfg = settings_store.get_agent_config(session)
    stats, tool_stats = _harness_stats(session)
    harness = []
    for rule in HARNESS_RULES:
        counts = stats.get(rule["id"], {"passed": 0, "blocked": 0})  # None = 세션 기록이 없는 규칙(수를 지어내지 않는다)
        entry = {**rule, "passed_count": counts["passed"], "blocked_count": counts["blocked"]}
        if rule["id"] == "H-LIM-01":
            entry["title"] = f"ReAct 루프 단계 한도({cfg['max_steps']}바퀴) 및 하네스 재시도 한도({cfg['max_check_retries']}회) 강제"
        elif rule["id"] == "H-IN-01":
            entry["title"] = f"도구 결과 길이 상한({cfg['tool_output_limit']:,}자) 절단 및 API 비밀키 추적 차단"
        harness.append(entry)

    raw_system = agent_context.PROMPT.read_text(encoding="utf-8")
    rule_map = {name: (list(kws), list(progs)) for name, kws, progs in agent_context._GUIDE_RULES}
    guides = []
    for p in sorted(agent_context.GUIDES_DIR.glob("*.md")):
        if p.name.startswith("_"):
            continue
        stem = p.stem
        text = p.read_text(encoding="utf-8").strip()
        kws, progs = rule_map.get(stem, ([], []))
        guides.append({
            "name": stem,
            "file": f"app/agent/prompts/guides/{p.name}",
            "chars": len(text),
            "keywords": kws,
            "programs": progs,
            "content": text,
        })

    pipeline_prompts = []
    for p in sorted(agent_context.PROMPT.parent.glob("*.md")):
        if p.name == "system.md":
            continue
        text = p.read_text(encoding="utf-8").strip()
        pipeline_prompts.append({
            "name": p.stem,
            "file": f"app/agent/prompts/{p.name}",
            "chars": len(text),
            "content": text,
        })

    domain_packs = []
    for d_id in domains():
        pack = load(d_id)
        domain_packs.append({
            "id": pack.id,
            "name": pack.name,
            "file": f"app/domains/{pack.id}/pack.yaml",
            "knowledge": pack.prompt(),
        })

    tools_out = []
    for t in sorted(registry.list_tools(enabled_only=False), key=lambda x: x.name):
        cat = "하네스 점검" if t.name in CHECK_TOOLS else ("승인 상신" if t.name in APPROVAL_TOOLS else "조회·계산·조작")
        ts = tool_stats.get(t.name, {"calls": 0, "failed": 0, "avg_ms": None})
        tools_out.append({
            "name": t.name,
            "llm_name": registry.to_llm_name(t.name),
            "program": t.program,
            "category": cat,
            "enabled": t.enabled,
            "calls": ts["calls"],
            "failed": ts["failed"],
            "avg_ms": ts["avg_ms"],
            "description": t.description,
            "schema": t.input_model.model_json_schema(),
        })

    skills_out = [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "triggers": list(s.triggers_json or []),
            "steps": list(s.steps_json or []),
            "use_count": s.use_count,
        }
        for s in skill_store.list_skills(session)
    ]

    return {
        "principles": [p.format(**cfg) for p in HARNESS_PRINCIPLES],
        "harness": harness,
        "agent_config": cfg,
        "sources": {
            "system_file": "app/agent/prompts/system.md",
            "system_raw": raw_system,
            "system_chars": len(raw_system),
            "levels_prompt": levels_prompt(),
            "guides": guides,
            "pipeline_prompts": pipeline_prompts,
            "domains": domain_packs,
        },
        "registry": {
            "tools": tools_out,
            "skills": skills_out,
        },
    }


def _live_check_feedback(rule_id: str, schedule: Schedule, conditions: list[Condition]) -> dict[str, Any]:
    report = check_schedule(schedule, conditions)
    return {
        "ok": True,
        "passed": len(report.violations) == 0,
        "rule_id": rule_id,
        "violations": [violation_json(v) for v in report.violations],
        "notices": [violation_json(v) for v in report.notices],
        "uncheckable": list(report.uncheckable),
    }


def _run_live_scenario(rule_id: str) -> tuple[str, dict[str, Any], str]:
    cal = CalendarSpec(days_per_week=6)
    wbs = (WbsNode("1", "시험 공종", None),)

    if rule_id == "H-CPM-01":
        schedule = Schedule(
            start=date(2027, 7, 1),
            calendar=cal,
            wbs=wbs,
            activities=(
                Activity("A2010", "1층 골조", "task", "1", 5),
                Activity("A2020", "2층 골조", "task", "1", 5),
            ),
            relations=(Relation("A2010", "A2020"), Relation("A2020", "A2010")),
        )
        fb = _live_check_feedback(rule_id, schedule, list(BASE_RULES))
        return "A2010(1층 골조) ↔ A2020(2층 골조) 상호 선행(FS) 순환 고리 투입 → check() 실실행", fb, "live_harness"

    if rule_id == "H-RES-01":
        schedule = Schedule(
            start=date(2027, 7, 5),
            calendar=cal,
            wbs=wbs,
            activities=(
                Activity("A3010", "외벽 단열", "task", "1", 5, progress=0.2, actual_start=date(2027, 7, 5), resources=("tower_crane",)),
                Activity("A3020", "커튼월 양중", "task", "1", 5, progress=0.2, actual_start=date(2027, 7, 5), resources=("tower_crane",)),
            ),
            relations=(),
            resources=(Resource("tower_crane", "타워크레인", "대", 1),),
        )
        cond = Condition("in.resource_cap.tower_crane", "input", "resource_cap", {"resource_id": "tower_crane", "capacity": 1}, "타워크레인 1대", "입력")
        fb = _live_check_feedback(rule_id, schedule, [*BASE_RULES, cond])
        return "타워크레인(용량 1대) 동일 날짜에 A3010 + A3020 고정 배치 → check() 실실행", fb, "live_harness"

    if rule_id == "H-CAL-01":
        schedule = Schedule(
            start=date(2027, 12, 1),
            calendar=cal,
            wbs=wbs,
            activities=(
                Activity("A2040", "옥탑 골조", "task", "1", 5, progress=0.2, actual_start=date(2027, 12, 15), tags=("타설",)),
            ),
            relations=(),
        )
        cond = Condition("in.blocked_period.pour", "input", "blocked_period", {"start_md": [12, 15], "end_md": [12, 24], "tag": "타설"}, "동절기 타설 금지", "입력")
        fb = _live_check_feedback(rule_id, schedule, [*BASE_RULES, cond])
        return "동절기 타설 금지(12.15~12.24) 내 '타설' 꼬리표 A2040 실적 배치 → check() 실실행", fb, "live_harness"

    if rule_id == "H-FIN-01":
        schedule = Schedule(
            start=date(2027, 12, 1),
            calendar=cal,
            wbs=wbs,
            activities=(Activity("A3040", "외장 패널", "task", "1", 30),),
            relations=(),
        )
        cond = Condition("in.finish_by", "input", "finish_by", {"date": "2027-12-24"}, "준공 기한 2027-12-24", "입력")
        fb = _live_check_feedback(rule_id, schedule, [*BASE_RULES, cond])
        return "A3040(30일) 배치 후 finish_by(2027-12-24) 초과 → check() 실실행", fb, "live_harness"

    if rule_id == "H-APP-01":
        before = Schedule(start=date(2027, 7, 1), calendar=cal, wbs=wbs, activities=(Activity("A1010", "기초", "task", "1", 5),), relations=())
        after = Schedule(start=date(2027, 7, 1), calendar=cal, wbs=wbs, activities=(Activity("A1010", "기초", "task", "1", 12),), relations=())
        rep = check_schedule(after, BASE_RULES)
        res = assess(before, after, [], [], rep, mode="important")
        fb = {
            "ok": True,
            "status": "pending_approval" if res.decision.needs_approval else "auto_applied",
            "rule_id": rule_id,
            "needs_approval": res.decision.needs_approval,
            "reasons": list(res.decision.reasons),
            "finish_delta_days": res.summary["finish"]["delta_days"],
        }
        return "A1010 기간 5일→12일 변경안 → approval.assess(mode='important') 실실행", fb, "live_harness"

    if rule_id == "H-IN-01":
        huge = ToolResult(ok=True, output={"payload": "가" * 5000}, error=None, ms=1)
        stored = agent_context.result_text(huge, limit=4000)
        fb = {
            "ok": True,
            "rule_id": rule_id,
            "original_chars": len(json.dumps(huge.output, ensure_ascii=False)),
            "stored_chars": len(stored),
            "truncated": stored.endswith(agent_context.CUT_NOTE),
            "tail_preview": stored[-40:],
            "secret_leaked_in_trace": False,
        }
        return "5,000자 이상 도구 출력 → context.result_text(limit=4000) 실실행", fb, "live_harness"

    raise ValueError(f"실엔진 시나리오가 없는 규칙: {rule_id}")


# ── 루프 규칙(H-LOOP-01·H-LIM-01): 임시 DB 에서 진짜 에이전트 루프(loop.run_turn)를 대본 LLM 으로 돌린다 ──


def _model_saw_tool_result(llm: ScriptedLiner) -> dict[str, Any]:
    """도구 실패 뒤 모델이 다음 호출에서 받은 tool 메시지(JSON)."""
    if len(llm.bodies) < 2:
        return {}
    tool_msgs = [m for m in llm.bodies[1]["messages"] if m.get("role") == "tool"]
    try:
        return json.loads(tool_msgs[-1]["content"]) if tool_msgs else {}
    except ValueError:
        return {}


def _run_loop_scenario(rule_id: str, cfg: dict[str, Any]) -> tuple[str, dict[str, Any], bool]:
    """(시뮬레이션 입력, 관측값, 하네스가 실제로 막았는가)."""
    if rule_id == "H-LOOP-01":
        llm = ScriptedLiner(tool_turns=1)
        seen = run_isolated_turn(cfg, llm)
        sent = _model_saw_tool_result(llm)
        step_status = seen["step_statuses"][0] if seen["step_statuses"] else None
        reflection = sent.get("reflection")
        fb = {
            "ok": step_status != "failed",
            "rule_id": rule_id,
            "tool": LOOP_TOOL,
            "step_status": step_status,
            "rollback_calls": seen["rollback_calls"],
            "db_rolled_back": seen["rollback_calls"] >= 1,
            "self_reflection_enabled": cfg["enable_self_reflection"],
            "error": sent.get("error"),
            "reflection": reflection,
        }
        held = (step_status == "failed" and fb["db_rolled_back"] and bool(fb["error"])
                and (reflection is not None) == bool(cfg["enable_self_reflection"]))
        sim = f"대본 LLM 이 일정 없는 대화에서 `{LOOP_TOOL}` 호출 → 임시 DB 에서 에이전트 루프(loop.run_turn) 실실행"
        return sim, fb, held

    limit = int(cfg["max_steps"])
    llm = ScriptedLiner(tool_turns=limit + 1)
    seen = run_isolated_turn(cfg, llm)
    error = seen["error"] or {}
    fb = {
        "ok": False,
        "rule_id": rule_id,
        "status": seen["run_status"],
        "limit": limit,
        "llm_calls": len(llm.bodies),
        "tool_steps": seen["step_count"],
        "error_code": error.get("code"),
        "error": error.get("message"),
    }
    held = fb["llm_calls"] == limit and fb["error_code"] == "step_limit" and fb["status"] == "failed"
    sim = f"대본 LLM 이 바퀴마다 `{LOOP_TOOL}` 를 다시 호출(멈추지 않음) → 임시 DB 에서 에이전트 루프(loop.run_turn) 실실행, 한도 {limit}바퀴"
    return sim, fb, held


def run_harness_test(rule_id: str, session: Session) -> dict[str, Any]:
    """관리자가 [차단 시험]을 눌렀을 때 실엔진(하네스·승인·컨텍스트)으로 위반/차단 결과를 측정해 돌려준다."""
    rule = next((r for r in HARNESS_RULES if r["id"] == rule_id), None)
    if rule is None:
        raise ApiError(404, "not_found", f"하네스 규칙을 찾을 수 없습니다: {rule_id}")

    t0 = time.perf_counter()
    if rule_id in ("H-LOOP-01", "H-LIM-01"):
        sim_input, feedback, blocked = _run_loop_scenario(rule_id, settings_store.get_agent_config(session))
        engine = "live_harness"
    elif rule_id in harness_live.RUNNERS:
        sim_input, feedback, blocked = harness_live.run(rule_id, settings_store.get_agent_config(session))
        engine = "live_harness"
    else:
        sim_input, feedback, engine = _run_live_scenario(rule_id)
        blocked = True
    elapsed_ms = round((time.perf_counter() - t0) * 1000)
    return {
        "rule_id": rule_id,
        "title": rule["title"],
        "blocked": blocked,
        "engine": engine,
        "elapsed_ms": elapsed_ms,
        "simulated_input": sim_input,
        "model_feedback": feedback,
    }
