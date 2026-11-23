import json

import httpx
import pytest

import app.tools.generate as generate_tools
from app.llm.client import LlmClient
from app.store.tables import ScheduleDraft
from app.tools.generate.extract_conditions import EXTRACT_SCHEMA
from app.tools.registry import call, list_tools
from tests.gen_doubles import (
    FINISH,
    SCHED_LATE_BY_1,
    SCHED_LATE_BY_3,
    SCHED_OK,
    START_FACT,
    WBS_OK,
    script,
    user_text,
)
from tests.llm_doubles import FakeLiner, add_connection, chat_body

_FIELDS = ("date", "resource_id", "capacity", "days_per_week", "holidays", "start_md", "end_md", "tag", "days")


def cond(kind: str, text: str, source: str = "프롬프트", **fields) -> dict:
    """LLM 이 내는 조건 한 줄(strict 모양: 안 쓰는 칸은 null)."""
    return {"kind": kind, "text": text, "source": source, **{f: fields.get(f) for f in _FIELDS}}


def extracted(conditions=(), facts=(), assumptions=(), unknown=()) -> dict:
    return {
        "conditions": list(conditions),
        "facts": list(facts),
        "assumptions": list(assumptions),
        "unknown": list(unknown),
    }


@pytest.fixture
def liner() -> FakeLiner:
    return FakeLiner()


@pytest.fixture(autouse=True)
def fake_llm(session, liner, monkeypatch):
    """도구가 쓰는 LLM 을 가짜 Liner 로 바꾼다(기본 연결 하나)."""
    add_connection(session)
    monkeypatch.setattr(generate_tools, "client_for", lambda ctx: LlmClient(ctx.session, transport=liner.transport))


def extract_args(**over) -> dict:
    return {"text": "5층 사무동, 2027년 11월 30일 준공", "domain": "construction", "level": "L3", **over}


def test_generate_tools_are_registered():
    specs = {t.name: t for t in list_tools()}
    assert {"generate.extract_conditions", "generate.run"} <= set(specs)
    assert not {"generate.make_wbs", "generate.make_schedule"} & set(specs)
    assert specs["generate.run"].mutates and not specs["generate.extract_conditions"].mutates  # run 은 초안을 저장한다


async def test_extract_builds_input_conditions_with_ids_and_sources(ctx, liner):
    script(liner, extracted(
        [
            cond("finish_by", "2027-11-30 준공", date="2027-11-30"),
            cond("resource_cap", "타워크레인 2대", "질문지", resource_id="tower_crane", capacity=2),
            cond("text_only", "민원 많은 지역", "가정"),
            cond("text_only", "야간 작업 없음", "질문지"),
            cond("blocked_period", "동절기 타설 금지", start_md=[12, 1], end_md=[2, 28], tag="타설"),
        ],
        facts=[{"label": "층수", "value": "지상 5층", "source": "프롬프트"}],
        assumptions=[{"label": "주 근무일", "value": "6일"}],
        unknown=["주요 자원 대수"],
    ))
    r = await call("generate.extract_conditions", extract_args(), ctx)
    assert r.ok, r.error
    out = r.output
    assert [(c["id"], c["layer"], c["source"]) for c in out["conditions"]] == [
        ("in.finish_by", "input", "프롬프트"),
        ("in.resource_cap.tower_crane", "input", "질문지"),
        ("in.text_only", "input", "가정"),
        ("in.text_only.2", "input", "질문지"),
        ("in.blocked_period.타설", "input", "프롬프트"),
    ]
    assert out["conditions"][0]["params"] == {"date": "2027-11-30"} and out["conditions"][2]["params"] == {}
    assert out["conditions"][4]["params"] == {"start_md": [12, 1], "end_md": [2, 28], "tag": "타설"}
    assert out["facts"] == [{"label": "층수", "value": "지상 5층", "source": "프롬프트"}]
    assert out["assumptions"] == [{"label": "주 근무일", "value": "6일", "source": "가정"}]
    assert out["unknown"] == ["주요 자원 대수"] and out["dropped"] == []


async def test_extract_drops_invalid_condition_and_reports_it(ctx, liner):
    script(liner, extracted([cond("finish_by", "준공", date="2027-13-45"), cond("max_duration", "한 작업 30일 이내", days=30)]))
    r = await call("generate.extract_conditions", extract_args(), ctx)
    assert [c["id"] for c in r.output["conditions"]] == ["in.max_duration"]
    assert r.output["dropped"] == [{"kind": "finish_by", "reason": "'date' 칸 값이 올바르지 않습니다: 날짜(YYYY-MM-DD)"}]


async def test_extract_drops_unknown_resource_id(ctx, liner):
    script(liner, extracted([cond("resource_cap", "굴착기 1대", resource_id="excavator", capacity=1)]))
    r = await call("generate.extract_conditions", extract_args(), ctx)
    assert r.output["conditions"] == []
    assert r.output["dropped"] == [{"kind": "resource_cap", "reason": "없는 자원입니다: excavator"}]


async def test_extract_drops_kind_not_allowed(ctx, liner):
    script(liner, extracted([cond("milestone_by", "골조 완료 9월", date="2027-09-30"), cond("no_cycle", "고리 없음")]))
    r = await call("generate.extract_conditions", extract_args(), ctx)
    assert r.output["conditions"] == []
    assert [d["kind"] for d in r.output["dropped"]] == ["milestone_by", "no_cycle"]
    assert r.output["dropped"][0]["reason"] == "쓸 수 없는 조건 종류입니다: milestone_by"


async def test_extract_calendar_without_holidays_uses_pack_default(ctx, liner):
    script(liner, extracted([cond("calendar", "주 5일 근무", days_per_week=5), cond("calendar", "공휴일 지정", days_per_week=6, holidays=["2027-04-01"])]))
    r = await call("generate.extract_conditions", extract_args(), ctx)
    params = [c["params"] for c in r.output["conditions"]]
    assert params == [{"days_per_week": 5, "holidays": "KR"}, {"days_per_week": 6, "holidays": ["2027-04-01"]}]
    assert [c["id"] for c in r.output["conditions"]] == ["in.calendar", "in.calendar.2"]


async def test_extract_request_is_light_strict_and_carries_answers_and_assumed(ctx, liner):
    script(liner, extracted())
    args = extract_args(
        answers=[{"question": "지하층이 있나요?", "answer": "지하 1층"}],
        assumed=[{"question": "타워크레인 몇 대?", "assumption": "1대로 가정"}],
    )
    r = await call("generate.extract_conditions", args, ctx)
    assert r.ok and r.output == {"conditions": [], "facts": [], "assumptions": [], "unknown": [], "dropped": []}
    body = liner.last_body
    assert body["routing_strategy"] == "cost"  # light
    assert body["response_format"]["json_schema"] == {"name": "result", "schema": EXTRACT_SCHEMA, "strict": True}
    text = user_text(liner, 0)
    assert "2027년 11월 30일 준공" in text and "지하 1층" in text and "1대로 가정" in text
    assert "공종별 액티비티, 선후 관계, 달력, 주요 자원" in text  # L3 에 꼭 있어야 하는 것


async def test_extract_drops_resource_cap_at_rough_levels(ctx, liner):
    script(liner, extracted([cond("resource_cap", "타워크레인 1대", resource_id="tower_crane", capacity=1)]))
    r = await call("generate.extract_conditions", extract_args(level="L2"), ctx)
    assert r.output["conditions"] == []
    assert r.output["dropped"] == [{"kind": "resource_cap", "reason": "개략 일정(L1·L2)에서는 자원을 다루지 않습니다."}]


async def test_extract_drops_dates_whose_year_is_not_in_the_text(ctx, liner):
    script(liner, extracted(
        [cond("finish_by", "11월 30일 준공", date="2026-11-30"), cond("max_duration", "한 작업 30일 이내", days=30)],
        facts=[{"label": "착공일", "value": "2026-12-01", "source": "프롬프트"}, {"label": "층수", "value": "5층", "source": "프롬프트"}],
        unknown=["준공 기한의 연도: '11월 30일'"],
    ))
    r = await call("generate.extract_conditions", extract_args(text="5층 사무동, 12월 1일 착공, 11월 30일 준공"), ctx)
    out = r.output
    assert [c["id"] for c in out["conditions"]] == ["in.max_duration"]
    assert out["facts"] == [{"label": "층수", "value": "5층", "source": "프롬프트"}]
    reason = "원문에 연도가 없는 날짜는 쓰지 않습니다."
    assert out["dropped"] == [{"kind": "finish_by", "reason": reason}, {"kind": "fact", "reason": reason}]
    assert out["unknown"] == ["준공 기한의 연도: '11월 30일'"]


async def test_extract_takes_the_year_from_answers_and_assumed(ctx, liner):
    script(liner, extracted(
        [cond("finish_by", "준공 기한", "질문지", date="2027-11-30"),
         cond("calendar", "공휴일", "가정", days_per_week=6, holidays=["2028-01-03"])],
    ))
    args = extract_args(
        text="5층 사무동 일정",
        answers=[{"question": "준공 기한은?", "answer": "2027-11-30"}],
        assumed=[{"question": "추가 휴일?", "assumption": "2028년 1월 3일 쉼"}],
    )
    r = await call("generate.extract_conditions", args, ctx)
    assert [c["id"] for c in r.output["conditions"]] == ["in.finish_by", "in.calendar"] and r.output["dropped"] == []


def test_extract_prompt_forbids_converting_yearless_dates():
    from app.agent.generation_steps import system_prompt
    from app.domains.loader import load

    text = system_prompt("extract", load("construction"))
    assert "연도·월·일" in text and "unknown" in text and "내년 3월" in text


async def test_extract_llm_failure_is_a_tool_error(ctx, liner):
    script(liner, httpx.ReadTimeout("느림"))
    r = await call("generate.extract_conditions", extract_args(), ctx)
    assert not r.ok and r.error == "응답이 너무 늦습니다."


async def test_extract_not_json_is_a_tool_error(ctx, liner):
    script(liner, "모르겠습니다")
    r = await call("generate.extract_conditions", extract_args(), ctx)
    assert not r.ok and r.error == "조건을 읽지 못했습니다. 다시 시도해 주세요."


@pytest.mark.parametrize("whole", [False, True], ids=["cut_json", "complete_json"])
async def test_extract_reply_cut_by_length_is_a_clear_tool_error(ctx, liner, whole):
    body = json.dumps(extracted(conditions=[cond("text_only", "야간 작업 금지")]), ensure_ascii=False)
    liner.push(chat_body(body if whole else body[:40], finish_reason="length"))  # 잘린 답은 모양이 맞아도 쓰지 않는다
    r = await call("generate.extract_conditions", extract_args(), ctx)
    assert not r.ok and r.error == "답이 길이 제한에 걸려 잘렸습니다. 요청을 나누어 다시 시도해 주세요."


async def test_extract_rejects_invalid_domain(ctx):
    r = await call("generate.extract_conditions", extract_args(domain="../ship"), ctx)
    assert not r.ok and r.error == "올바르지 않은 분야입니다: ../ship"


async def test_extract_accepts_custom_domain_and_dynamic_resources(ctx, liner):
    script(
        liner,
        extracted(
            [cond("resource_cap", "선임 연구원 2명", "프롬프트", resource_id="senior_researcher", capacity=2)],
            facts=[{"label": "시작일", "value": "2027-03-02", "source": "프롬프트"}],
        ),
    )
    r = await call("generate.extract_conditions", extract_args(domain="rnd", text="2027년 3월 2일 시작 전고체 배터리 R&D"), ctx)
    assert r.ok, r.error
    assert [c["id"] for c in r.output["conditions"]] == ["in.resource_cap.senior_researcher"]
    assert r.output["dropped"] == []


def run_args(**over) -> dict:
    finish_by = {"id": "in.finish_by", "layer": "input", "kind": "finish_by", "params": {"date": FINISH},
                 "text": f"{FINISH} 준공", "source": "프롬프트"}
    return {"domain": "construction", "level": "L3", "request": "5층 사무동", "facts": [START_FACT],
            "conditions": [finish_by], "assumptions": [], **over}


async def test_run_generates_and_stores_draft(ctx, liner, session, events):
    script(liner, WBS_OK, SCHED_LATE_BY_3, SCHED_OK)
    r = await call("generate.run", run_args(), ctx)
    assert r.ok, r.error
    out = r.output
    assert out["ok"] and out["finish"] == FINISH and out["activity_count"] == 4 and out["critical_count"] == 4
    assert out["rounds"] == [{"n": 1, "activity_count": 4, "violations": 1}, {"n": 2, "activity_count": 4, "violations": 0}]
    assert out["violations"] == [] and out["notices"] == [] and out["conflict"] == [] and out["reason"] is None
    assert out["warnings"] == ["액티비티가 4개입니다. L3는 50~100개입니다."]
    assert out["assumptions"] == [{  # 고침이 골조를 23일 → 20일로 줄였다(A1)
        "label": "A1020 1층 골조 기간", "value": "조건을 맞추려 23일 → 20일(근무일)로 줄였습니다 — 확인 필요",
        "source": "고침", "evidence_ids": []}]
    assert session.get(ScheduleDraft, out["draft_id"]) is not None
    stages = {e.data["stage"] for e in events if e.type == "card" and e.data["kind"] == "generation"}
    assert stages == {"wbs", "schedule", "compute", "critical", "check"}


async def test_run_reports_violations_at_the_limit(ctx, liner):
    # 기본 한도 5회. 위반이 회차마다 달라야 한도까지 돈다(같은 위반이 이어지면 먼저 멈춘다)
    script(liner, WBS_OK, SCHED_LATE_BY_3, SCHED_LATE_BY_1, SCHED_LATE_BY_3, SCHED_LATE_BY_1, SCHED_LATE_BY_3)
    r = await call("generate.run", run_args(), ctx)
    assert r.ok and not r.output["ok"] and r.output["conflict"] == ["in.finish_by"] and len(r.output["rounds"]) == 5
    v = r.output["violations"][0]
    assert v["condition_id"] == "in.finish_by" and v["amount"] == 3 and v["message"] == "준공이 기한보다 3일 늦습니다."
    assert r.output["reason"] == "조건을 모두 맞추지 못했습니다." and r.output["draft_id"] is not None


async def test_run_rejects_unreadable_condition(ctx):
    bad = {"id": "in.finish_by", "layer": "input", "kind": "finish_by", "params": {}, "text": "준공", "source": "프롬프트"}
    r = await call("generate.run", run_args(conditions=[bad]), ctx)
    assert not r.ok and r.error == "조건을 읽을 수 없습니다: in.finish_by: 'date' 칸이 없습니다."


async def test_run_rejects_invalid_domain(ctx):
    r = await call("generate.run", run_args(domain="../ship"), ctx)
    assert not r.ok and r.error == "올바르지 않은 분야입니다: ../ship"


async def test_run_llm_down(ctx, liner, session):
    script(liner, httpx.ReadTimeout("느림"))
    r = await call("generate.run", run_args(), ctx)
    assert r.ok and not r.output["ok"] and r.output["draft_id"] is None and r.output["finish"] is None
    assert "늦습니다" in r.output["reason"] and session.query(ScheduleDraft).count() == 0


async def test_run_keeps_best_draft_when_llm_fails(ctx, liner, session):
    script(liner, WBS_OK, SCHED_LATE_BY_3, httpx.ReadTimeout("느림"))
    r = await call("generate.run", run_args(), ctx)
    out = r.output
    assert r.ok and not out["ok"] and out["draft_id"] is not None and out["conflict"] == ["in.finish_by"]
    assert out["reason"].startswith("LLM 호출이 실패해 지금까지 가장 나은 초안(1회차, 위반 1)을 저장했습니다.")
    assert out["finish"] == "2027-04-08" and session.get(ScheduleDraft, out["draft_id"]) is not None


async def test_run_removes_resource_cap_at_rough_levels(ctx, liner):
    script(liner, WBS_OK, SCHED_OK)
    crane = {"id": "in.resource_cap.tower_crane", "layer": "input", "kind": "resource_cap",
             "params": {"resource_id": "tower_crane", "capacity": 1}, "text": "타워크레인 1대", "source": "질문지"}
    r = await call("generate.run", run_args(level="L1", conditions=[crane]), ctx)
    assert r.output["ok"] and len(r.output["rounds"]) == 1
    assert "개략 일정(L1·L2)에서는 자원을 다루지 않습니다." in r.output["warnings"]


async def test_run_reports_unchecked_conditions_and_result_card(ctx, liner, events):
    script(liner, WBS_OK, SCHED_OK)
    r = await call("generate.run", run_args(), ctx)
    out = r.output
    assert out["ok"] and {"id": "construction.curing", "name": next(
        u["name"] for u in out["uncheckable"] if u["id"] == "construction.curing")} in out["uncheckable"]
    assert len(out["uncheckable"]) == 4 and out["invalid"] == []
    card = [e.data for e in events if e.type == "card" and e.data["kind"] == "generation_result"]
    assert card == [{
        "kind": "generation_result", "ok": True, "draft_id": out["draft_id"], "finish": FINISH,
        "activity_count": 4, "critical_count": 4, "assumptions": [], "violations": [],
        "uncheckable_count": 4, "invalid_count": 0, "conflict": [], "reason": None,
    }]
    spec = {t.name: t for t in list_tools()}["generate.run"]
    assert "ok 는 자동 점검한 조건만의 결과입니다. uncheckable 의 조건은 점검하지 않았으니 통과로 말하지 마세요." in spec.description


async def test_extract_output_feeds_run(ctx, liner):
    script(liner, extracted([cond("finish_by", "준공 기한", date=FINISH)], facts=[START_FACT]), WBS_OK, SCHED_OK)
    first = await call("generate.extract_conditions", extract_args(), ctx)
    args = run_args(conditions=first.output["conditions"], facts=first.output["facts"])
    r = await call("generate.run", args, ctx)
    assert r.ok and r.output["ok"] and r.output["finish"] == FINISH
