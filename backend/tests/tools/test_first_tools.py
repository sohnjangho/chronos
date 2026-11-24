"""첫 도구 셋: schedule.read · calc.cpm · ui.open_window."""

import re
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.events import AgentEvent
from app.core.model import Relation, Resource
from app.store.schedules import to_json
from app.store.tables import ScheduleVersion
from app.tools.registry import call, list_tools
from tests.schedules import make, store, task

# ── 작업 지시서의 시험 ──────────────────────────────────────────────


async def test_open_window_emits_event(ctx, events):
    await call("ui.open_window", {"program": "gantt", "params": {"id": "1"}}, ctx)
    assert events[-1].type == "open_window" and events[-1].data["program"] == "gantt"


# ── 덧붙인 시험 ─────────────────────────────────────────────────────


@pytest.fixture
def sched_ctx(ctx, sid):
    """sample_schedule(A 3일 → B 2일)을 대상으로 하는 문맥."""
    return replace(ctx, schedule_id=sid)


def test_specs():
    specs = {t.name: t for t in list_tools()}
    # Task 16b 리뷰 I1: 일정판(schedule)이 나뉘었다 — 일정 읽기는 스케줄, 경로 계산은 CPM 프로그램 도구.
    assert (specs["schedule.read"].program, specs["schedule.read"].mutates) == ("schedule-table", False)
    assert (specs["calc.cpm"].program, specs["calc.cpm"].mutates) == ("cpm", False)
    assert all(specs[n].program in OPENABLE for n in ("schedule.read", "calc.cpm"))
    assert (specs["ui.open_window"].program, specs["ui.open_window"].mutates) == (None, False)
    assert all(specs[n].description for n in ("schedule.read", "calc.cpm", "ui.open_window"))


async def test_open_window_output_and_event(ctx, events):
    r = await call("ui.open_window", {"program": "gantt", "params": {"id": "1"}}, ctx)
    assert (r.ok, r.output) == (True, {"opened": True})
    assert events == [AgentEvent("open_window", {"program": "gantt", "params": {"id": "1"}, "explicit": True})]
    r = await call("ui.open_window", {"program": "chat"}, ctx)
    assert r.ok and events[-1].data == {"program": "chat", "params": {}, "explicit": True}


async def test_open_window_rejects_bad_input(ctx, events):
    assert (await call("ui.open_window", {}, ctx)).ok is False
    assert (await call("ui.open_window", {"program": "x", "params": {"n": {"a": 1}}}, ctx)).ok is False
    assert events == []


async def test_open_window_rejects_a_misspelled_field(ctx, events):
    r = await call("ui.open_window", {"program": "gantt", "param": {"id": "1"}}, ctx)
    assert r.ok is False and r.error.startswith("입력 형식 오류: param: ") and events == []


# Task 16b: 일정판(schedule)은 스케줄·간트차트·CPM·공정률 프로그램으로 나뉘었다. 도구는 화면에 있는 프로그램만 연다.
OPENABLE = [
    "chat", "questionnaire", "workflow", "approvals", "explorer", "settings", "devconsole",
    "schedule-table", "gantt", "cpm", "progress", "compare", "conditions", "delays", "reports", "contacts", "library", "projects", "points",
]


def test_open_window_offers_the_screen_programs_by_id_and_name():
    spec = {t.name: t for t in list_tools()}["ui.open_window"]
    schema = spec.input_model.model_json_schema()
    assert schema["properties"]["program"]["enum"] == OPENABLE
    for text in ("schedule-table(스케줄", "gantt(간트차트", "cpm(CPM", "progress(공정률", "compare(비교판", "delays(지연 기록", "reports(보고서", "library(자료함", "devconsole(개발 콘솔", "contacts(연락처", "projects(프로젝트 관리", "points(관리 포인트"):
        assert text in spec.description
    assert "일정판" not in spec.description


FRONTEND_PROGRAMS = Path(__file__).resolve().parents[3] / "frontend" / "src" / "programs"


def _registered_ids() -> list[str]:
    """화면 등록부(frontend/src/programs/index.ts 가 import 하는 프로그램)의 manifest id."""
    index = (FRONTEND_PROGRAMS / "index.ts").read_text(encoding="utf-8")
    folders = re.findall(r"^import \w+ from '\./([\w-]+)';", index, re.MULTILINE)
    manifests = [(FRONTEND_PROGRAMS / f / "index.ts").read_text(encoding="utf-8") for f in folders]
    return [re.search(r"^\s+id: '([^']+)'", m, re.MULTILINE)[1] for m in manifests]


# Task 16b 리뷰 minor 4: 에이전트가 열 수 있는 프로그램 = 화면에 등록한 프로그램. Docker 의 backend 컨테이너에는
# frontend 가 붙어 있지 않아 건너뛴다(맥에서 직접 돌릴 때 본다).
@pytest.mark.skipif(not FRONTEND_PROGRAMS.is_dir(), reason="frontend 폴더가 없다(Docker backend 컨테이너)")
def test_open_window_lists_exactly_the_registered_screen_programs():
    spec = {t.name: t for t in list_tools()}["ui.open_window"]
    enum = spec.input_model.model_json_schema()["properties"]["program"]["enum"]
    assert sorted(enum) == sorted(_registered_ids())


@pytest.mark.parametrize("program", ["schedule", "schedule-board", "x"])
async def test_open_window_rejects_a_program_that_is_not_on_screen(ctx, events, program):
    r = await call("ui.open_window", {"program": program}, ctx)
    assert r.ok is False and r.error.startswith("입력 형식 오류: program: ") and events == []


async def test_schedule_read_summary(sched_ctx, events):
    r = await call("schedule.read", {}, sched_ctx)
    assert r.ok is True and r.error is None and events == []
    assert r.output == {
        "name": "시험 일정",
        "domain": "construction",
        "level": "L3",
        "version": 1,
        "finish": "2027-03-05",
        "activity_count": 2,
        "critical": ["A", "B"],
        "condition_count": 0,
        "summary": {"critical_count": 2, "negative_float_count": 0, "warning_count": 0},
    }


async def test_schedule_read_counts_conditions_and_only_critical_ids(ctx, session):
    # A(3) → B(2), C(1) 은 따로: C 는 여유가 있다.
    schedule = make([task("A", 3), task("B", 2), task("C", 1)], [Relation("A", "B")])
    sid = store(session, schedule, conditions=[{"id": "c1"}, {"id": "c2"}])
    r = await call("schedule.read", {}, replace(ctx, schedule_id=sid))
    assert r.output["critical"] == ["A", "B"] and r.output["activity_count"] == 3
    assert r.output["condition_count"] == 2 and r.output["summary"]["critical_count"] == 2


async def test_schedule_read_matches_schedule_api(client, admin, sched_ctx, sid):
    view = client.get(f"/api/schedules/{sid}", headers=admin).json()
    out = (await call("schedule.read", {}, sched_ctx)).output
    assert out["finish"] == view["finish"] and out["summary"] == {k: view["summary"][k] for k in out["summary"]}
    assert out["critical"] == [a["id"] for a in view["activities"] if a["critical"]]


@pytest.mark.parametrize("name", ["schedule.read", "calc.cpm"])
async def test_missing_schedule_id_fails_with_message(ctx, name):
    r = await call(name, {}, ctx)
    assert (r.ok, r.output, r.error) == (False, None, "대상 일정이 없습니다.")


@pytest.mark.parametrize("name", ["schedule.read", "calc.cpm"])
async def test_unknown_schedule_is_explained(ctx, name):
    r = await call(name, {}, replace(ctx, schedule_id=999))
    assert (r.ok, r.output, r.error) == (False, None, "일정을 찾을 수 없습니다.")


CYCLE = make([task("A", 1), task("B", 1)], [Relation("A", "B"), Relation("B", "A")])


@pytest.mark.parametrize("name", ["schedule.read", "calc.cpm"])
async def test_uncomputable_schedule_is_explained(sched_ctx, session, sid, name):
    session.get(ScheduleVersion, (sid, 1)).snapshot_json = to_json(CYCLE)
    session.commit()
    r = await call(name, {}, sched_ctx)
    assert (r.ok, r.output, r.error) == (False, None, "선후 관계가 고리를 이룹니다.")


@pytest.mark.parametrize("name", ["schedule.read", "calc.cpm"])
async def test_extra_arguments_are_rejected(sched_ctx, name):
    r = await call(name, {"schedule_id": 99}, sched_ctx)
    assert r.ok is False and r.error.startswith("입력 형식 오류")


async def test_calc_cpm_rows(sched_ctx):
    r = await call("calc.cpm", {}, sched_ctx)
    assert r.ok is True
    assert r.output == {
        "finish": "2027-03-05",
        "activities": [
            {"id": "A", "es": "2027-03-01", "ef": "2027-03-03", "ls": "2027-03-01", "lf": "2027-03-03",
             "tf": 0, "ff": 0, "critical": True},
            {"id": "B", "es": "2027-03-04", "ef": "2027-03-05", "ls": "2027-03-04", "lf": "2027-03-05",
             "tf": 0, "ff": 0, "critical": True},
        ],
    }


async def test_calc_cpm_uses_resource_leveling_like_the_view(client, admin, ctx, session):
    # 크레인 1대를 A·B 가 같이 쓴다: 맞춤 뒤에는 하나가 뒤로 밀린다.
    crane = Resource("crane", "타워크레인", "대", 1)
    schedule = make([task("A", 3, resources=("crane",)), task("B", 2, resources=("crane",))], resources=[crane])
    sid = store(session, schedule)
    view = client.get(f"/api/schedules/{sid}", headers=admin).json()
    out = (await call("calc.cpm", {}, replace(ctx, schedule_id=sid))).output
    assert out["finish"] == view["finish"] == "2027-03-05"
    assert [(a["id"], a["es"], a["ef"], a["tf"], a["critical"]) for a in out["activities"]] == [
        (a["id"], a["es"], a["ef"], a["tf"], a["critical"]) for a in view["activities"]
    ]


# Task 25 fix 1 (I1): 관리자 전용 프로그램은 도구로도 일반 사용자에게 열지 않는다.
async def test_open_window_refuses_devconsole_for_a_non_admin(ctx, events):
    r = await call("ui.open_window", {"program": "devconsole"}, replace(ctx, user=SimpleNamespace(role="user")))
    assert r.ok is False and r.error == "관리자만 열 수 있는 프로그램입니다: 개발 콘솔" and events == []
    assert (await call("ui.open_window", {"program": "devconsole"}, ctx)).ok is True
    assert events[-1].data["program"] == "devconsole"


@pytest.mark.skipif(not FRONTEND_PROGRAMS.is_dir(), reason="frontend 폴더가 없다(Docker backend 컨테이너)")
def test_admin_only_list_matches_the_screen_manifests():
    from app.tools.ui.open_window import ADMIN_ONLY

    folders = re.findall(r"^import \w+ from '\./([\w-]+)';", (FRONTEND_PROGRAMS / "index.ts").read_text(encoding="utf-8"), re.MULTILINE)
    admin = {
        re.search(r"^\s+id: '([^']+)'", t, re.MULTILINE)[1]
        for t in ((FRONTEND_PROGRAMS / f / "index.ts").read_text(encoding="utf-8") for f in folders)
        if re.search(r"^\s+adminOnly: true", t, re.MULTILINE)
    }
    assert set(ADMIN_ONLY) == admin


# Task 56: 자료함은 누구나 연다(관리자 전용 아님).
async def test_open_window_opens_the_library_for_anyone(ctx, events):
    r = await call("ui.open_window", {"program": "library"}, replace(ctx, user=SimpleNamespace(role="user")))
    assert r.ok is True and events[-1] == AgentEvent("open_window", {"program": "library", "params": {}, "explicit": True})


async def test_create_project_creates_starter_schedule_and_binds_chat(session, ctx, events):
    from app.store import chats
    from app.store.schedules import load

    chat = chats.create_chat(session, user_id=1, schedule_id=None)
    r = await call(
        "schedule.create_project",
        {"name": "해외 설비 조달", "domain": "procurement", "level": "L2", "start": "2027-05-03", "days_per_week": 5},
        replace(ctx, chat_session_id=chat.id),
    )
    assert r.ok is True
    sid = r.output["schedule_id"]
    assert (r.output["name"], r.output["domain"], r.output["level"], r.output["version"]) == (
        "해외 설비 조달", "procurement", "L2", 1,
    )
    sched, conditions, version = load(session, sid)
    assert version == 1 and conditions == [] and [a.id for a in sched.activities] == ["MS-START", "A-01", "MS-END"]
    assert chats.get_chat(session, chat.id).schedule_id == sid
    assert events[-1].type == "card" and events[-1].data["kind"] == "project_created" and events[-1].data["schedule_id"] == sid


# Task 75: 연락처는 현장 관리자에게 없다(화면 매니페스트의 noField 와 같게 — 맞춤 시험이 있다).
async def test_open_window_refuses_contacts_for_a_field_manager(ctx, events):
    r = await call("ui.open_window", {"program": "contacts", "params": {"contact": "3"}}, replace(ctx, user=SimpleNamespace(role="field")))
    assert r.ok is False and r.error == "현장 관리자는 열 수 없는 프로그램입니다: 연락처" and events == []
    r = await call("ui.open_window", {"program": "contacts", "params": {"contact": "3"}}, replace(ctx, user=SimpleNamespace(role="user")))
    assert r.ok is True and events[-1] == AgentEvent("open_window", {"program": "contacts", "params": {"contact": "3"}, "explicit": True})


@pytest.mark.skipif(not FRONTEND_PROGRAMS.is_dir(), reason="frontend 폴더가 없다(Docker backend 컨테이너)")
def test_no_field_list_matches_the_screen_manifests():
    from app.tools.ui.open_window import NO_FIELD

    folders = re.findall(r"^import \w+ from '\./([\w-]+)';", (FRONTEND_PROGRAMS / "index.ts").read_text(encoding="utf-8"), re.MULTILINE)
    no_field = {
        re.search(r"^\s+id: '([^']+)'", t, re.MULTILINE)[1]
        for t in ((FRONTEND_PROGRAMS / f / "index.ts").read_text(encoding="utf-8") for f in folders)
        if re.search(r"^\s+noField: true", t, re.MULTILINE)
    }
    assert set(NO_FIELD) == no_field == {"contacts", "projects"}
