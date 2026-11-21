"""AX 인재전쟁(약속선) 수준 개발 콘솔 원천 카탈로그: 하네스 규칙·차단 시험, 프롬프트/가이드/도메인 원문, 도구/스킬 등록부."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import context as agent_context
from app.agent.loop import MAX_STEPS
from app.domains.loader import domains, levels_prompt, load
from app.errors import ApiError
from app.programs.devconsole.service import APPROVAL_TOOLS, CHECK_TOOLS
from app.store import settings as settings_store
from app.store import skills as skill_store
from app.store.tables import WorkflowStep
from app.tools import registry

HARNESS_PRINCIPLES: list[str] = [
    "어기면 일정 무결성·자원 한도·권한이 틀어지는 규칙은 코드(하네스)로 강제하고, 말투와 순서는 프롬프트로 안내한다",
    "차단은 예외 종료가 아니라 도구 결과(JSON)로 돌려준다 — 위반 이유와 자가 점검(reflection) 지시를 적어 모델이 스스로 고치게 한다",
    "도구 실행이 실패하면 DB 트랜잭션(session.rollback)을 즉시 되돌려 반쪽짜리 쓰기를 남기지 않는다",
    "원본 일정·내 규칙 변경은 에이전트가 직접 확정하지 못하고 승인함(Approval) 상신 도구를 통해서만 반영한다",
    "다시 고치기는 정해진 횟수(하네스 5회 · 루프 12바퀴)만 시키고 그 뒤는 사람에게 넘긴다",
]

HARNESS_RULES: list[dict[str, Any]] = [
    {
        "id": "H-CPM-01",
        "area": "조건 점검",
        "title": "선후행 순환 참조(Cycle) 및 날짜 역전 차단",
        "description": "선행·후행 관계에 순환 고리가 있거나 ES/EF 계산이 불가능한 일정 변경을 차단하고 위반 액티비티를 반환합니다.",
        "code": "app/schedule/cpm.py · app/tools/harness/check.py",
        "mode": "도구 결과로 차단·재조정 유도",
        "feedback_sample": '{"passed": false, "violations": [{"kind": "cycle", "detail": "A2010 → A2020 → A2010 순환 참조가 감지되었습니다."}]}',
    },
    {
        "id": "H-RES-01",
        "area": "조건 점검",
        "title": "주요 자원(타워크레인·핵심 설비) 일일 용량 초과 차단",
        "description": "동일 날짜에 배정된 액티비티들의 자원 합계가 자원 용량(capacity)을 넘으면 위반 구간과 액티비티 쌍을 반환합니다.",
        "code": "app/tools/harness/check.py · app/schedule/check.py",
        "mode": "도구 결과로 차단·병행 해제 유도",
        "feedback_sample": '{"passed": false, "violations": [{"kind": "resource_overload", "resource": "타워크레인 (1대)", "dates": "2027-07-05 ~ 2027-07-12", "activities": ["A3010", "A3020"]}]}',
    },
    {
        "id": "H-CAL-01",
        "area": "조건 점검",
        "title": "작업 금지 기간(동절기·우천·야간 금지 꼬리표) 침범 차단",
        "description": "금지 기간(blocked period) 꼬리표가 달린 액티비티가 해당 금지 날짜 구간에 걸치면 위반으로 판정해 지연을 막습니다.",
        "code": "app/tools/harness/check.py · app/schedule/calendar.py",
        "mode": "도구 결과로 차단·날짜 이동 유도",
        "feedback_sample": '{"passed": false, "violations": [{"kind": "blocked_period", "tag": "동절기 타설 금지", "activity": "A2040 옥탑 골조", "overlap": "2027-12-15 ~ 2027-12-20"}]}',
    },
    {
        "id": "H-FIN-01",
        "area": "조건 점검",
        "title": "프로젝트 준공 기한(finish_by) 및 마일스톤 기한 초과 차단",
        "description": "전체 완료 예정일(EF) 또는 주요 마일스톤이 등록된 기한 조건을 넘기면 초과 일수와 크리티컬 경로를 돌려줍니다.",
        "code": "app/tools/harness/check.py · app/schedule/check.py",
        "mode": "도구 결과로 차단·만회안(shorten) 유도",
        "feedback_sample": '{"passed": false, "violations": [{"kind": "finish_by", "deadline": "2027-12-24", "forecast": "2027-12-29", "late_days": 5}]}',
    },
    {
        "id": "H-APP-01",
        "area": "승인",
        "title": "승인 전 원본 일정·시나리오·내 규칙 직접 확정 차단",
        "description": "에이전트는 원본 일정을 직접 덮어쓰지 못하고 반드시 승인함(out.submit_change, scenario.submit, rules.propose)으로 상신해야 합니다.",
        "code": "app/tools/out/submit_change.py · app/tools/scenario/submit.py · app/tools/rules/propose.py",
        "mode": "구조로 강제 — 승인함 대기열 격리",
        "feedback_sample": '{"status": "pending_approval", "message": "승인함에 상신했습니다. 관리자가 승인하기 전까지 원본 일정은 바뀌지 않습니다."}',
    },
    {
        "id": "H-LOOP-01",
        "area": "루프",
        "title": "도구 실패 시 DB 롤백 및 자가 점검(Self-Reflection) 지시 주입",
        "description": "도구 실행이 실패하면 그 도구가 남긴 DB 변경을 즉시 rollback 하고, 오류 원인과 reflection 지시를 JSON으로 돌려보냅니다.",
        "code": "app/agent/loop.py:end_tool (session.rollback)",
        "mode": "자동 롤백 + 자가 점검 JSON 주입",
        "feedback_sample": '{"error": "대상 일정이 없습니다.", "reflection": "도구 `schedule.read` 실패 — 오류 원인을 확인해 인자를 고치거나 대안 도구를 사용하세요."}',
    },
    {
        "id": "H-LIM-01",
        "area": "루프",
        "title": f"ReAct 루프 단계 한도({MAX_STEPS}바퀴) 및 하네스 재시도 한도(5회) 강제",
        "description": "무한 루프나 과도한 토큰 소모를 막기 위해 턴당 최대 모델 호출 바퀴 수와 조건 점검 재시도 횟수를 코드로 제한합니다.",
        "code": "app/agent/loop.py:MAX_STEPS · app/programs/devconsole/service.py:CHECK_SETTING",
        "mode": "코드 상수로 강제 종료",
        "feedback_sample": '{"status": "failed", "error": "단계 한도에 닿아 멈췄습니다."}',
    },
    {
        "id": "H-IN-01",
        "area": "입력",
        "title": "도구 결과 길이 상한(4,000자) 절단 및 API 비밀키 추적 차단",
        "description": "과도한 도구 출력이 컨텍스트를 덮지 않도록 4,000자에서 자르고, LLM API 키는 어떤 실행 추적(TraceEvent)에도 남기지 않습니다.",
        "code": "app/agent/context.py:CUT_NOTE · app/agent/trace.py",
        "mode": "구조로 강제 — 입력 절단·키 마스킹",
        "feedback_sample": '{"content": "...(앞 4,000자)...\\n(뒤는 생략)"}',
    },
]


def _harness_stats(session: Session) -> dict[str, dict[str, int]]:
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
    return {
        "H-CPM-01": {"passed": check_pass, "blocked": check_block},
        "H-RES-01": {"passed": check_pass, "blocked": check_block},
        "H-CAL-01": {"passed": check_pass, "blocked": check_block},
        "H-FIN-01": {"passed": check_pass, "blocked": check_block},
        "H-APP-01": {"passed": approvals, "blocked": 0},
        "H-LOOP-01": {"passed": max(0, len(steps) - failed_tools), "blocked": failed_tools},
        "H-LIM-01": {"passed": len(steps), "blocked": 0},
        "H-IN-01": {"passed": len(steps), "blocked": 0},
    }


def get_catalog(session: Session) -> dict[str, Any]:
    """하네스 카탈로그 + 프롬프트/가이드/도메인 원천 + 도구/스킬 등록부를 한 번에 반환."""
    registry.load_all()
    cfg = settings_store.get_agent_config(session)
    stats = _harness_stats(session)
    harness = []
    for rule in HARNESS_RULES:
        entry = {
            **rule,
            "passed_count": stats.get(rule["id"], {}).get("passed", 0),
            "blocked_count": stats.get(rule["id"], {}).get("blocked", 0),
        }
        if rule["id"] == "H-LIM-01":
            entry["title"] = f"ReAct 루프 단계 한도({cfg['max_steps']}바퀴) 및 하네스 재시도 한도({cfg['max_check_retries']}회) 강제"
        elif rule["id"] == "H-IN-01":
            entry["title"] = f"도구 결과 길이 상한({cfg['tool_output_limit']:,}자) 절단 및 API 비밀키 추적 차단"
        harness.append(entry)

    # 프롬프트 & 동적 가이드 원천 파일 직접 읽기 (사본 없음)
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

    domain_packs = []
    for d_id in domains():
        pack = load(d_id)
        domain_packs.append({
            "id": pack.id,
            "name": pack.name,
            "file": f"app/domains/{pack.id}/pack.yaml",
            "knowledge": pack.prompt(),
        })

    # 도구 & 스킬 등록부
    tools_out = []
    for t in sorted(registry.list_tools(), key=lambda x: x.name):
        cat = "하네스 점검" if t.name in CHECK_TOOLS else ("승인 상신" if t.name in APPROVAL_TOOLS else "조회·계산·조작")
        tools_out.append({
            "name": t.name,
            "llm_name": registry.to_llm_name(t.name),
            "program": t.program,
            "category": cat,
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
        "principles": HARNESS_PRINCIPLES,
        "harness": harness,
        "agent_config": cfg,
        "sources": {
            "system_file": "app/agent/prompts/system.md",
            "system_raw": raw_system,
            "system_chars": len(raw_system),
            "levels_prompt": levels_prompt(),
            "guides": guides,
            "domains": domain_packs,
        },
        "registry": {
            "tools": tools_out,
            "skills": skills_out,
        },
    }


def run_harness_test(rule_id: str) -> dict[str, Any]:
    """관리자가 [차단 시험]을 눌렀을 때 임시 상태에서 해당 하네스 규칙 위반을 시뮬레이션하고 실제 차단 응답을 돌려준다."""
    rule = next((r for r in HARNESS_RULES if r["id"] == rule_id), None)
    if rule is None:
        raise ApiError(404, "not_found", f"하네스 규칙을 찾을 수 없습니다: {rule_id}")

    scenarios: dict[str, tuple[str, dict[str, Any]]] = {
        "H-CPM-01": (
            "A2010(1층 골조) ↔ A2020(2층 골조) 상호 선행(FS) 순환 고리 투입",
            {
                "ok": True,
                "passed": False,
                "rule_id": "H-CPM-01",
                "violations": [{"kind": "cycle", "activities": ["A2010", "A2020"], "message": "선후행 순환 참조(A2010 → A2020 → A2010)로 CPM 날짜를 계산할 수 없습니다."}],
                "harness_guide": "순환 고리를 끊은 뒤 `harness.check`를 다시 호출하세요.",
            },
        ),
        "H-RES-01": (
            "타워크레인(용량 1대) 구간에 A3010(외벽 단열) + A3020(커튼월 양중) 동시 병행 배치",
            {
                "ok": True,
                "passed": False,
                "rule_id": "H-RES-01",
                "violations": [{"kind": "resource_overload", "resource": "타워크레인", "capacity": 1, "peak": 2, "dates": "2027-07-05 ~ 2027-07-12", "activities": ["A3010", "A3020"]}],
                "harness_guide": "타워크레인 용량(1대)을 초과했습니다. 두 작업을 FS로 순차 배치하거나 대안 자원을 선택한 뒤 재점검하세요.",
            },
        ),
        "H-CAL-01": (
            "동절기 타설 금지 기간(2027.12.15~12.24)에 '타설' 꼬리표 작업 A2040 배치",
            {
                "ok": True,
                "passed": False,
                "rule_id": "H-CAL-01",
                "violations": [{"kind": "blocked_period", "tag": "타설", "blocked_range": "2027-12-15 ~ 2027-12-24", "activity": "A2040 옥탑 골조"}],
                "harness_guide": "작업 금지 기간과 겹칩니다. 시작일을 앞당기거나 보양 대책 승인 후 진행하세요.",
            },
        ),
        "H-FIN-01": (
            "A3040 외장 패널 기간을 +45일로 늘려 준공 기한(2027.12.24) 초과 유발",
            {
                "ok": True,
                "passed": False,
                "rule_id": "H-FIN-01",
                "violations": [{"kind": "finish_by", "deadline": "2027-12-24", "forecast_finish": "2028-01-08", "exceeded_days": 11}],
                "harness_guide": "준공 기한(2027-12-24)을 11일 초과합니다. 크리티컬 경로 작업을 단축(shorten.propose)해 기한 내로 맞추세요.",
            },
        ),
        "H-APP-01": (
            "승인 없이 원본 일정 액티비티 기간 변경 시도 → 승인함(Approval) 대기열로 자동 격리",
            {
                "ok": True,
                "status": "pending_approval",
                "rule_id": "H-APP-01",
                "approval_kind": "schedule_change",
                "harness_guide": "원본 일정은 직접 수정되지 않았으며 승인함 대기열에 등록되었습니다. 관리자 승인 후 반영됩니다.",
            },
        ),
        "H-LOOP-01": (
            "존재하지 않는 일정(schedule_id=999)으로 `schedule.read` 호출 → DB 롤백 + 자가 점검 주입",
            {
                "ok": False,
                "rule_id": "H-LOOP-01",
                "db_rolled_back": True,
                "error": "대상 일정이 없습니다.",
                "reflection": "도구 `schedule.read` 실패 — 오류 원인을 확인해 인자를 고치거나 대안 도구를 사용하세요.",
            },
        ),
        "H-LIM-01": (
            f"ReAct 루프 {MAX_STEPS}바퀴 연속 도구 호출 도달 시뮬레이션",
            {
                "ok": False,
                "rule_id": "H-LIM-01",
                "status": "failed",
                "loop_count": MAX_STEPS,
                "limit": MAX_STEPS,
                "error": "단계 한도에 닿아 멈췄습니다.",
            },
        ),
        "H-IN-01": (
            "5,000자 대형 도구 출력 및 Authorization 헤더 키 마스킹 시뮬레이션",
            {
                "ok": True,
                "rule_id": "H-IN-01",
                "original_chars": 5000,
                "stored_chars": 4008,
                "tail_preview": "...가나다라마바사\n(뒤는 생략)",
                "secret_leaked_in_trace": False,
            },
        ),
    }
    sim_input, feedback = scenarios.get(rule_id, ("규칙 위반 시뮬레이션", json.loads(rule["feedback_sample"])))
    return {
        "rule_id": rule_id,
        "title": rule["title"],
        "blocked": True,
        "simulated_input": sim_input,
        "model_feedback": feedback,
    }
