"""새 핵심 읽기/보고서 도구 6종 + 하네스 재시도 설정(max_check_retries) 연동 시험."""

from dataclasses import replace

import pytest

import app.tools.generate as generate_tools
from app.core.model import Relation, Resource, WbsNode
from app.harness.conditions import Condition
from app.llm.client import LlmClient
from app.programs.reports import service as reports_service
from app.store import settings as settings_store
from app.store.schedules import create_schedule
from app.tools.registry import call, list_tools
from tests import schedules
from tests.gen_doubles import FINISH, SCHED_LATE_BY_3, START_FACT, WBS_OK, script
from tests.llm_doubles import FakeLiner, add_connection


def _rich_schedule():
    base = schedules.make(
        [
            schedules.task("A", 4, wbs="1.1", resources=("crane",), tags=("타설",)),
            schedules.task("B", 3, wbs="1.1", resources=(), tags=("마감",)),
        ],
        [Relation("A", "B", "FS", 1)],
        [Resource("crane", "타워크레인", "대", 1)],
    )
    return replace(
        base,
        wbs=(WbsNode("1", "건축", None), WbsNode("1.1", "골조", "1")),
    )


async def test_new_tools_are_registered():
    names = {t.name for t in list_tools()}
    assert {
        "progress.read",
        "schedule.list",
        "conditions.list",
        "schedule.activity_detail",
        "report.list_templates",
        "report.revise",
    } <= names


async def test_progress_read_and_schedule_list(session, ctx):
    ok_sid = schedules.store(session, _rich_schedule())
    late_sid = create_schedule(
        session,
        name="위험 일정",
        domain="construction",
        level="L3",
        schedule=_rich_schedule(),
        conditions=[
            Condition("in.finish_by", "input", "finish_by", {"date": "2027-03-01"}, "기한 초과", "프롬프트").to_dict()
        ],
        by_kind="agent",
        by_name="에이전트",
        note="시험",
    )
    session.commit()

    p = await call("progress.read", {}, replace(ctx, schedule_id=ok_sid))
    assert p.ok, p.error
    assert p.output["schedule_id"] == ok_sid
    assert "plan_now" in p.output and "actual_now" in p.output
    assert "wbs" in p.output and "lookahead" in p.output
    assert "curve" not in p.output

    ls = await call("schedule.list", {}, ctx)
    assert ls.ok, ls.error
    assert ls.output["total"] == 2
    assert ls.output["danger_count"] == 1
    assert ls.output["ok_count"] == 1

    danger = await call("schedule.list", {"level": "danger"}, ctx)
    assert danger.ok, danger.error
    assert len(danger.output["items"]) == 1
    assert danger.output["items"][0]["id"] == late_sid


async def test_conditions_list_reads_state_and_resources(session, ctx):
    cond = Condition("in.finish_by", "input", "finish_by", {"date": "2027-03-01"}, "기한 초과", "프롬프트").to_dict()
    sid = schedules.store(session, _rich_schedule(), conditions=[cond])
    session.commit()

    all_res = await call("conditions.list", {}, replace(ctx, schedule_id=sid))
    assert all_res.ok, all_res.error
    assert all_res.output["resources"] == [{"id": "crane", "name": "타워크레인", "unit": "대", "capacity": 1}]
    fin = next(c for c in all_res.output["conditions"] if c["id"] == "in.finish_by")
    assert fin["state"] == "violated" and "늦습니다" in fin["message"]

    only_input = await call("conditions.list", {"layer": "input", "enabled_only": True}, replace(ctx, schedule_id=sid))
    assert only_input.ok, only_input.error
    assert [c["id"] for c in only_input.output["conditions"]] == ["in.finish_by"]


async def test_activity_detail_by_id_resource_tag_and_validation(session, ctx):
    sid = schedules.store(session, _rich_schedule())
    session.commit()
    sctx = replace(ctx, schedule_id=sid)

    by_id = await call("schedule.activity_detail", {"activity_id": "a"}, sctx)
    assert by_id.ok, by_id.error
    d = by_id.output["detail"]
    assert d["id"] == "A"
    assert d["od"] == 4
    assert d["wbs_path"] == "1 건축 > 1.1 골조"
    assert d["resources"] == ["crane"] and d["tags"] == ["타설"]
    assert d["predecessors"] == []
    assert d["successors"] == [{"id": "B", "name": "작업 B", "type": "FS", "lag": 1, "critical": True}]

    by_res = await call("schedule.activity_detail", {"resource_id": "타워크레인"}, sctx)
    assert by_res.ok, by_res.error
    assert [m["id"] for m in by_res.output["matches"]] == ["A"]

    by_tag = await call("schedule.activity_detail", {"tag": "마감"}, sctx)
    assert by_tag.ok, by_tag.error
    assert [m["id"] for m in by_tag.output["matches"]] == ["B"]

    missing = await call("schedule.activity_detail", {}, sctx)
    assert not missing.ok and "입력 형식 오류" in missing.error


async def test_report_list_templates_and_revise(session, ctx, events):
    sid = schedules.store(session, _rich_schedule())
    session.commit()
    sctx = replace(ctx, schedule_id=sid)

    tpls = await call("report.list_templates", {"cadence": "monthly"}, sctx)
    assert tpls.ok, tpls.error
    assert len(tpls.output["builtins"]) >= 1

    gen = await call("report.generate", {"cadence": "monthly", "period_label": "2027년 3월"}, sctx)
    assert gen.ok, gen.error
    rep = reports_service.get_report(session, sid, gen.output["report_id"])
    blk = next(b for b in rep.blocks if b.block_kind == "prose")

    rev = await call(
        "report.revise",
        {"report_id": rep.id, "block_id": blk.id, "instruction": "리스크 대응 문구 추가", "remember_rule": True},
        sctx,
    )
    assert rev.ok, rev.error
    assert rev.output["block_id"] == blk.id and rev.output["updated_text"]
    assert any(e.type == "card" and e.data["kind"] == "report" for e in events)


async def test_generate_run_respects_max_check_retries_setting(session, ctx, monkeypatch):
    add_connection(session)
    liner = FakeLiner()
    monkeypatch.setattr(generate_tools, "client_for", lambda c: LlmClient(c.session, transport=liner.transport))
    settings_store.set_agent_config(session, {"max_check_retries": 2})
    try:
        script(liner, WBS_OK, SCHED_LATE_BY_3, SCHED_LATE_BY_3)
        args = {
            "domain": "construction",
            "level": "L3",
            "request": "5층 사무동",
            "facts": [START_FACT],
            "conditions": [Condition("in.finish_by", "input", "finish_by", {"date": FINISH}, "준공 기한", "프롬프트").to_dict()],
            "assumptions": [],
        }
        r = await call("generate.run", args, ctx)
        assert r.ok, r.error
        assert not r.output["ok"] and len(r.output["rounds"]) == 2
    finally:
        settings_store.set_agent_config(session, {"max_check_retries": 5})
