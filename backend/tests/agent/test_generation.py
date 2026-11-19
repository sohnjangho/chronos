from datetime import date, timedelta

import httpx
from sqlalchemy import func, select

from app.agent.generation import GenRound, generate
from app.agent.generation_steps import (
    DATE_RULE,
    REPAIR_SCHEMA,
    SCHEDULE_SCHEMA,
    WBS_SCHEMA,
    system_prompt,
)
from app.core.cpm import compute
from app.domains.loader import levels_prompt, load
from app.store.schedules import to_json
from app.store.tables import LlmCall, ScheduleDraft, ScheduleVersion
from tests.gen_doubles import (
    CRANE_CAP,
    FINISH,
    FINISH_BY,
    SCHED_BAD_WBS,
    SCHED_CYCLE,
    SCHED_LATE_BY_1,
    SCHED_LATE_BY_3,
    SCHED_OK,
    SCHED_OK_WITH_FAKE_DATES,
    SCHED_PARALLEL_CRANE,
    START_FACT,
    WBS_OK,
    act,
    input_condition,
    sched,
    script,
    system_text,
    user_text,
)
from tests.llm_doubles import FakeLiner


async def gen(ctx, llm, *, level="L3", facts=(START_FACT,), inputs=(), assumptions=(), max_rounds=5):
    return await generate(
        ctx, llm, domain="construction", level=level, request="5층 사무동 신축 일정",
        facts=list(facts), inputs=list(inputs), assumptions=list(assumptions), max_rounds=max_rounds,
    )


def drafts(session) -> int:
    return session.scalar(select(func.count()).select_from(ScheduleDraft))


# ── 지시서 시험(새 입력에 맞춤) ─────────────────────────────────────


async def test_happy_path_three_rounds(ctx, llm, liner):
    script(liner, WBS_OK, SCHED_LATE_BY_3, SCHED_LATE_BY_1, SCHED_OK)
    r = await gen(ctx, llm, inputs=[FINISH_BY])
    assert r.ok and [x.violations for x in r.rounds] == [1, 1, 0] and r.report.violations == []
    assert [x.n for x in r.rounds] == [1, 2, 3] and len(liner.requests) == 4  # WBS 는 한 번만
    assert compute(r.schedule).finish == date.fromisoformat(FINISH) and r.reason is None and r.conflict == []


async def test_llm_dates_are_ignored(ctx, llm, liner):
    script(liner, WBS_OK, SCHED_OK_WITH_FAKE_DATES)
    r = await gen(ctx, llm)
    assert compute(r.schedule).rows["A1010"].es == date(2027, 3, 2)  # 03.01은 공휴일 → 코드가 계산
    assert r.schedule.start == date(2027, 3, 1) and all(a.constraint is None for a in r.schedule.activities)


async def test_cyclic_draft_is_retried_not_saved(ctx, llm, liner, session):
    script(liner, WBS_OK, SCHED_CYCLE, SCHED_OK)
    r = await gen(ctx, llm)
    assert r.ok and r.rounds[0].violations == -1 and r.rounds[1].violations == 0
    assert session.query(ScheduleVersion).count() == 0 and drafts(session) == 1
    assert "고리" in user_text(liner, 2)  # 오류 내용이 LLM 에 돌아간다


async def test_not_json_is_retried(ctx, llm, liner):
    script(liner, WBS_OK, "죄송합니다", SCHED_OK)
    r = await gen(ctx, llm)
    assert r.ok and [x.violations for x in r.rounds] == [-1, 0] and r.rounds[0].activity_count == 0
    assert "JSON" in user_text(liner, 2)


async def test_unsatisfiable_stops_at_limit_and_names_conflict(ctx, llm, liner):
    script(liner, WBS_OK, *[SCHED_LATE_BY_3] * 9)
    r = await gen(ctx, llm, inputs=[FINISH_BY], max_rounds=3)
    assert not r.ok and len(r.rounds) == 3 and r.conflict == ["in.finish_by"] and r.schedule is not None
    assert r.reason == "조건을 모두 맞추지 못했습니다." and r.draft_id is not None and len(liner.requests) == 4


async def test_best_draft_is_kept_at_the_limit(ctx, llm, liner):
    script(liner, WBS_OK, SCHED_LATE_BY_3, SCHED_LATE_BY_1, SCHED_CYCLE)
    r = await gen(ctx, llm, inputs=[FINISH_BY], max_rounds=3)
    assert [x.violations for x in r.rounds] == [1, 1, -1] and not r.ok
    assert compute(r.schedule).finish == date(2027, 4, 6)  # 위반 수가 같으면 나중 안(하루 늦음)
    assert r.report.violations[0].amount == 1


async def test_llm_down_gives_reason_and_no_draft(ctx, llm, liner, session):
    script(liner, httpx.ReadTimeout("느림"))
    r = await gen(ctx, llm)
    assert not r.ok and r.schedule is None and "늦습니다" in r.reason and drafts(session) == 0
    assert r.draft_id is None and r.report is None


async def test_llm_failure_keeps_best_draft_so_far(ctx, llm, liner, session):
    script(liner, WBS_OK, SCHED_CYCLE, SCHED_LATE_BY_3, httpx.ConnectError("끊김"))
    r = await gen(ctx, llm, inputs=[FINISH_BY])
    assert not r.ok and r.schedule is not None and drafts(session) == 1 and r.draft_id is not None
    assert r.conflict == ["in.finish_by"] and [x.violations for x in r.rounds] == [-1, 1]
    assert r.reason.startswith("LLM 호출이 실패해 지금까지 가장 나은 초안(2회차, 위반 1)을 저장했습니다.")
    assert "연결할 수 없습니다" in r.reason  # 실패 까닭도 붙는다
    row = session.get(ScheduleDraft, r.draft_id)
    assert row.schedule_json == to_json(r.schedule) and row.report_json["violations"][0]["condition_id"] == "in.finish_by"


async def test_llm_not_ready_gives_reason_and_no_draft(ctx, llm_empty, session):
    r = await gen(ctx, llm_empty)
    assert not r.ok and r.schedule is None and "연결" in r.reason and drafts(session) == 0


async def test_key_resources_attached_by_tag(ctx, llm, liner):
    script(liner, WBS_OK, SCHED_OK)
    r = await gen(ctx, llm)
    frame = next(a for a in r.schedule.activities if "골조" in a.name)
    assert "tower_crane" in frame.resources and frame.tags == ("골조",)
    rebar = next(a for a in r.schedule.activities if a.id == "A1010")
    assert set(rebar.resources) == {"rebar_crew", "tower_crane"} and rebar.tags == ("철근",)
    assert {x.id: x.capacity for x in r.schedule.resources} == {
        "tower_crane": 1, "rebar_crew": 1, "form_crew": 1, "pour_crew": 1
    }


async def test_generation_cards_are_emitted(ctx, llm, liner, events):
    script(liner, WBS_OK, SCHED_OK)
    await gen(ctx, llm)
    cards = [e.data for e in events if e.type == "card"]
    assert [c["stage"] for c in cards] == ["wbs", "schedule", "compute", "critical", "check"]
    assert all(c["kind"] == "generation" for c in cards)
    assert cards[0]["rounds"] == [] and cards[-1]["rounds"] == [{"n": 1, "activity_count": 4, "violations": 0}]


# ── 판단(R11)으로 더한 시험 ─────────────────────────────────────────


async def test_missing_wbs_reference_is_broken_and_explained(ctx, llm, liner):
    script(liner, WBS_OK, SCHED_BAD_WBS, SCHED_OK)
    r = await gen(ctx, llm)
    assert r.ok and r.rounds == [GenRound(1, 5, -1), GenRound(2, 4, 0)]
    assert "9.9" in user_text(liner, 2)


async def test_broken_wbs_reply_is_retried(ctx, llm, liner):
    script(liner, "WBS 를 만들 수 없습니다", WBS_OK, SCHED_OK)
    r = await gen(ctx, llm)
    assert r.ok and [x.violations for x in r.rounds] == [-1, 0] and "JSON" in user_text(liner, 1)


async def test_all_broken_gives_no_schedule(ctx, llm, liner, session):
    script(liner, WBS_OK, "아니요", SCHED_CYCLE)
    r = await gen(ctx, llm, max_rounds=2)
    assert not r.ok and r.schedule is None and r.report is None and drafts(session) == 0
    assert r.reason and r.conflict == [] and len(r.rounds) == 2


async def test_start_date_assumed_when_unknown(ctx, llm, liner):
    script(liner, WBS_OK, SCHED_OK)
    r = await gen(ctx, llm, facts=[], assumptions=[{"label": "층수", "value": "5층", "source": "가정"}])
    today = date.today()
    monday = today + timedelta(days=7 - today.weekday())
    assert r.schedule.start == monday
    assert r.assumptions == [
        {"label": "층수", "value": "5층", "source": "가정"},
        {"label": "착공일", "value": f"착공일을 알 수 없어 {monday.isoformat()}로 가정했습니다.", "source": "가정"},
    ]


async def test_start_after_condition_wins_over_facts(ctx, llm, liner):
    script(liner, WBS_OK, SCHED_OK)
    start = input_condition("in.start_after", "start_after", {"date": "2027-03-08"}, "3월 8일 착공")
    r = await gen(ctx, llm, inputs=[start])
    assert r.schedule.start == date(2027, 3, 8) and r.assumptions == []


async def test_level_fit_warning_reaches_repair_prompt_once(ctx, llm, liner):
    script(liner, WBS_OK, SCHED_LATE_BY_3, SCHED_LATE_BY_1, SCHED_OK)
    r = await gen(ctx, llm, inputs=[FINISH_BY])
    warning = "액티비티가 4개입니다. L3는 50~100개입니다."
    assert r.ok and r.warnings == [warning]
    assert warning in user_text(liner, 2) and warning not in user_text(liner, 3)
    assert "준공이 기한보다 3일 늦습니다." in user_text(liner, 2)


async def test_level_fit_alone_does_not_trigger_repair(ctx, llm, liner):
    script(liner, WBS_OK, SCHED_OK)
    r = await gen(ctx, llm, level="L1")
    assert r.ok and len(r.rounds) == 1 and len(liner.requests) == 2
    assert r.warnings == ["WBS 깊이가 3단계입니다. L1는 1~2단계입니다.", "액티비티가 4개입니다. L1는 10~20개입니다."]


async def test_resource_cap_is_removed_at_rough_levels(ctx, llm, liner):
    script(liner, WBS_OK, SCHED_OK)
    r = await gen(ctx, llm, level="L2", inputs=[CRANE_CAP, FINISH_BY])
    assert r.ok and len(r.rounds) == 1
    assert "개략 일정(L1·L2)에서는 자원을 다루지 않습니다." in r.warnings
    assert "in.resource_cap.tower_crane" not in [c.id for c in r.conditions]
    assert "tower_crane" not in user_text(liner, 1).split("지킬 조건:")[1]


async def test_start_fact_needs_an_exact_start_label(ctx, llm, liner):
    script(liner, WBS_OK, SCHED_OK)
    other = {"label": "외부 마감 시작", "value": "2027-09-01", "source": "프롬프트"}
    r = await gen(ctx, llm, facts=[other])
    today = date.today()
    assert r.schedule.start == today + timedelta(days=7 - today.weekday())
    assert r.assumptions[-1]["label"] == "착공일"


async def test_exact_start_labels_are_accepted(ctx, llm, liner):
    script(liner, WBS_OK, SCHED_OK)
    r = await gen(ctx, llm, facts=[{"label": "착수일", "value": "2027-05-03(월)", "source": "질문지"}])
    assert r.schedule.start == date(2027, 5, 3) and r.assumptions == []


async def test_uncheckable_and_invalid_conditions_are_reported(ctx, llm, liner):
    script(liner, WBS_OK, SCHED_OK)
    first = input_condition("in.text_only", "text_only", {}, "민원 많은 지역")
    again = input_condition("in.text_only", "text_only", {}, "야간 작업 없음")
    r = await gen(ctx, llm, inputs=[first, again])
    curing = next(c for c in r.conditions if c.id == "construction.curing")
    assert r.ok and {"id": "construction.curing", "name": curing.text} in r.uncheckable
    assert {"id": "in.text_only", "name": "야간 작업 없음"} in r.uncheckable
    assert r.invalid == [{"id": "in.text_only", "reason": "같은 id 의 조건이 뒤에 다시 있습니다."}]


async def test_broken_round_keeps_the_previous_violations_in_feedback(ctx, llm, liner):
    script(liner, WBS_OK, SCHED_LATE_BY_3, SCHED_CYCLE, SCHED_OK)
    r = await gen(ctx, llm, inputs=[FINISH_BY])
    assert r.ok and [x.violations for x in r.rounds] == [1, -1, 0]
    text = user_text(liner, 3)
    assert "고리" in text and "준공이 기한보다 3일 늦습니다." in text


async def test_huge_duration_is_broken_and_loop_continues(ctx, llm, liner):
    script(liner, WBS_OK, sched(10**9), sched(3651), SCHED_OK)
    r = await gen(ctx, llm)
    assert r.ok and [x.violations for x in r.rounds] == [-1, -1, 0]
    assert "od" in user_text(liner, 2)


async def test_long_lag_is_broken(ctx, llm, liner):
    late = sched(20)
    late["activities"][2]["predecessors"][0]["lag"] = 366
    script(liner, WBS_OK, late, SCHED_OK)
    r = await gen(ctx, llm)
    assert r.ok and [x.violations for x in r.rounds] == [-1, 0]


async def test_overflow_while_computing_is_a_broken_draft(ctx, llm, liner, monkeypatch):
    from app.agent import generation

    real, calls = generation.check_schedule, []

    def flaky(schedule, conditions):
        calls.append(1)
        if len(calls) == 1:
            raise OverflowError("date value out of range")
        return real(schedule, conditions)

    monkeypatch.setattr(generation, "check_schedule", flaky)
    script(liner, WBS_OK, SCHED_OK, SCHED_OK)
    r = await gen(ctx, llm)
    assert r.ok and [x.violations for x in r.rounds] == [-1, 0]
    assert "날짜 계산이 범위를 넘었습니다" in user_text(liner, 2)


async def test_level_without_resources_attaches_none(ctx, llm, liner):
    script(liner, WBS_OK, SCHED_OK)
    r = await gen(ctx, llm, level="L1")
    assert r.schedule.resources == () and all(a.resources == () for a in r.schedule.activities)
    assert next(a for a in r.schedule.activities if a.id == "A1020").tags == ("골조",)


async def test_unknown_llm_tags_are_dropped_known_and_condition_tags_kept(ctx, llm, liner):
    slab = act("A1015", "1층 슬래브", "1.2.1", 3, ["A1010"], tags=["타설", "아무거나", "야간"])
    script(liner, WBS_OK, sched(20, extra=[slab]))
    night = input_condition("in.blocked_period.야간", "blocked_period", {"start_md": [7, 1], "end_md": [7, 31], "tag": "야간"}, "7월 야간 금지")
    r = await gen(ctx, llm, inputs=[night])
    a = next(x for x in r.schedule.activities if x.id == "A1015")
    assert a.tags == ("타설", "야간") and a.resources == ("pour_crew",)
    assert "야간" in user_text(liner, 1)  # 쓸 수 있는 꼬리표로 알려 준다


async def test_notices_do_not_trigger_repair(ctx, llm, liner):
    script(liner, WBS_OK, SCHED_PARALLEL_CRANE)
    r = await gen(ctx, llm, inputs=[CRANE_CAP])
    assert r.ok and len(r.rounds) == 1 and len(liner.requests) == 2
    assert [n.condition_id for n in r.report.notices] == ["in.resource_cap.tower_crane"]


async def test_draft_stored_without_pinned_start(ctx, llm, liner, session):
    script(liner, WBS_OK, SCHED_PARALLEL_CRANE)
    r = await gen(ctx, llm, inputs=[CRANE_CAP])
    row = session.get(ScheduleDraft, r.draft_id)
    assert all("pinned_start" not in a for a in row.schedule_json["activities"])
    assert all(a.pinned_start is None for a in r.schedule.activities)
    assert row.schedule_json == to_json(r.schedule)


async def test_draft_row_keeps_conditions_report_and_assumptions(ctx, llm, liner, session):
    script(liner, WBS_OK, SCHED_OK)
    r = await gen(ctx, llm, facts=[], inputs=[FINISH_BY])
    row = session.get(ScheduleDraft, r.draft_id)
    ids = [c["id"] for c in row.conditions_json]
    assert ids[:4] == ["base.no_cycle", "base.no_dangling", "base.calendar", "base.valid"]
    assert "construction.curing" in ids and ids[-1] == "in.finish_by"
    assert [c.id for c in r.conditions] == ids
    assert (row.domain, row.level, row.chat_session_id) == ("construction", "L3", None)
    assert row.report_json["violations"] == [] and "in.finish_by" in row.report_json["passed"]
    assert "construction.curing" in row.report_json["uncheckable"]
    assert row.assumptions_json == r.assumptions and row.assumptions_json[0]["label"] == "착공일"


class WatchingLiner(FakeLiner):
    """답하기 전에 부른 쪽 세션에 쓰기(쌓인 변경·열린 쓰기 트랜잭션)가 있는지 적는다."""

    def __init__(self, session) -> None:
        super().__init__()
        self.session = session
        self.pending: list[bool] = []

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        s = self.session
        open_write = s.connection().connection.dbapi_connection.in_transaction
        self.pending.append(bool(s.new or s.dirty or s.deleted) or open_write)
        return await super()._handle(request)


async def test_no_pending_writes_while_llm_call_is_in_flight(ctx, session):
    from app.llm.client import LlmClient
    from tests.llm_doubles import add_connection

    add_connection(session)
    watch = WatchingLiner(session)
    script(watch, WBS_OK, SCHED_CYCLE, SCHED_LATE_BY_3, SCHED_OK)
    r = await gen(ctx, LlmClient(session, transport=watch.transport), inputs=[FINISH_BY])
    assert r.ok and watch.pending == [False] * 4
    assert session.scalar(select(func.count()).select_from(LlmCall)) == 4  # 기록이 막히지 않았다


async def test_calls_use_hard_purpose_and_strict_schemas(ctx, llm, liner):
    script(liner, WBS_OK, SCHED_LATE_BY_3, SCHED_OK)
    await gen(ctx, llm, inputs=[FINISH_BY])
    formats = [b["response_format"]["json_schema"] for b in liner.bodies]
    assert [f["schema"] for f in formats] == [WBS_SCHEMA, SCHEDULE_SCHEMA, REPAIR_SCHEMA]
    assert all(f["strict"] is True for f in formats)
    assert all(b["routing_strategy"] == "quality" for b in liner.bodies)  # hard


def _strict(schema: dict) -> bool:
    """strict 모드 규칙: 객체마다 모든 속성이 required, additionalProperties false."""
    if "anyOf" in schema:
        return all(_strict(s) for s in schema["anyOf"])
    if schema.get("type") == "object":
        props = schema["properties"]
        own = set(schema["required"]) == set(props) and schema["additionalProperties"] is False
        return own and all(_strict(p) for p in props.values())
    if schema.get("type") == "array":
        return _strict(schema["items"])
    return True


def test_schemas_follow_strict_rules():
    assert all(_strict(s) for s in (WBS_SCHEMA, SCHEDULE_SCHEMA, REPAIR_SCHEMA))
    assert "date" not in str(SCHEDULE_SCHEMA) and "es" not in SCHEDULE_SCHEMA["properties"]


def test_prompts_include_levels_domain_and_date_rule():
    pack = load("construction")
    for name in ("extract", "wbs", "schedule", "repair"):
        text = system_prompt(name, pack)
        assert levels_prompt() in text and pack.prompt() in text and DATE_RULE in text
    assert DATE_RULE == "날짜는 계산하지 않는다 — 기간(근무일)과 선후 관계만 낸다"


async def test_system_prompts_are_sent(ctx, llm, liner):
    script(liner, WBS_OK, SCHED_LATE_BY_3, SCHED_OK)
    await gen(ctx, llm, inputs=[FINISH_BY])
    pack = load("construction")
    assert [system_text(liner, n) for n in range(3)] == [
        system_prompt("wbs", pack), system_prompt("schedule", pack), system_prompt("repair", pack)
    ]
