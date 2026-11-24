"""shorten.make — 단축안(만회안) 복사본을 만들고 비교판을 연다. 저장된 일정은 바꾸지 않는다.

0. 지금 버전보다 낮은 버전으로 만든 열린 만회안·지연 반영안은 버린다(discarded, W4). 승인함에 올라간 안은 그대로.
1. 기준 원본: 지금 버전에 열린 지연 사건을 넣은 것(store.delays.delayed_base, include_open_delays 가 거짓이면 사건 없이).
   열린 사건이 있으면 그것만 넣은 "지연 반영안 (n건)"(source delay)을 기준으로 둔다 — 같은 버전·같은 사건 묶음이고
   스냅숏·조건까지 같은 열린 지연 반영안이 있으면 그것을 쓴다(사건을 고쳤으면 새로 만든다).
2. 목표(근무일): target_days → 기준 준공이 켜진 finish_by 가운데 가장 이른 기한을 넘으면 기한까지 → Plan 준공
   (store.view.plan_of, 마지막 계획 변경 때 고정한 예측)을 넘으면 Plan 까지 → 없으면 ToolError.
3. core.shorten 의 묶음(이동이 있는 것)마다 복사본(source shorten): 일정 = apply_moves(기준 원본, resources=False),
   자원 추가는 입력 조건 in.resource_cap.<자원>(source "단축안")으로 넣는다(같은 id 는 바꿈).
   묶음마다 당김 효과(core.accel — 당긴 일수 pulled_days·경고 accel_warn·다음 결정 줄 next_chain)를 요약에 넣는다.
4. 설명·추천은 LLM(hard, strict JSON)이 쓴다. 날짜가 든 설명은 버리고, 만든 안에 없는 추천은 버린다. LLM 이 실패하거나
   추천을 버리면 코드가 고른다: 도달 → 위반 적음 → 이동 적음 → 이득 큼 → key 순. 날짜·이득·위반은 모두 코드 값이다.
LLM 을 부르기 전에 복사본을 commit 한다(부르는 동안 쓰기 잠금을 쥐지 않는다). 설명·추천은 그 뒤 flush 만 한다.
사건: card {kind: "shorten_options", …}(출력과 같음) → open_window {program: "compare", params: {id, base, other}}.
"""

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.context import PROMPT
from app.agent.events import AgentEvent
from app.core.accel import accel_effect
from app.core.calendar import WorkCalendar
from app.core.cpm import compute
from app.core.model import Schedule
from app.core.resources import level
from app.core.shorten import Move, Package, ShortenResult, apply_moves, shorten
from app.harness.assemble import assemble_all, prepare_stored
from app.harness.conditions import Condition, condition_problem, read_conditions
from app.llm.client import LlmClient, LlmFailed, LlmNotReady
from app.store import approvals, scenarios
from app.store.delays import delayed_base
from app.store.schedules import load, run, to_json
from app.store.settings import accel_warn_ratio, points_config
from app.store.tables import Scenario
from app.store.view import plan_of
from app.tools.context import ToolContext, ToolError, explained_schedule_errors
from app.tools.points.accel_check import ChainItem, chain_items
from app.tools.registry import tool

NO_TARGET_MESSAGE = "줄일 목표가 없습니다. 며칠 당길지 알려 주세요(target_days)."
NOTHING_MESSAGE = "줄일 방법을 찾지 못했습니다. 실적이 없는 크리티컬 작업에 병행·압축·자원 추가를 할 곳이 없습니다."
DELAY_NAME = "지연 반영안 ({}건)"  # programs/delays 의 지연 반영안과 같은 이름
CONDITION_SOURCE = "단축안"
NOTE_PROMPT = PROMPT.parent / "shorten_note.md"
# 설명 글에 이런 날짜가 있으면 그 설명은 버린다(LLM 은 날짜를 계산하지 않는다)
DATE_IN_TEXT = re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}월\s*\d{1,2}일|\d{4}\.\s?\d{1,2}\.\s?\d{1,2}")
_KEY = {"type": "string", "enum": ["A", "B", "C"]}
SHORTEN_NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "recommended": {"anyOf": [_KEY, {"type": "null"}]},
        "notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"key": _KEY, "note": {"type": "string"}},
                "required": ["key", "note"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["recommended", "notes"],
    "additionalProperties": False,
}


def client_for(ctx: ToolContext) -> LlmClient:
    """도구가 쓰는 LLM. 시험은 이 함수를 바꿔 가짜 LLM 을 넣는다."""
    return LlmClient(ctx.session)


class ShortenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_days: int | None = Field(default=None, ge=1, le=365, description="당길 근무일. 사용자가 며칠이라고 했을 때만")
    include_open_delays: bool = Field(default=True, description="아직 일정에 넣지 않은 지연 사건을 기준에 넣을지")


class OptionOut(BaseModel):
    scenario_id: int
    key: str  # A | B | C
    name: str
    finish: str  # 복사본 준공(YYYY-MM-DD)
    gain: int  # 기준 준공에서 당긴 근무일(= 준공 반영 일수)
    reached: bool  # 목표만큼 당겼는가
    pulled_days: int  # 묶음이 당긴 일수(압축 od 차 + 병행 선행 od − lag, 자원 추가 0) — 「준공 반영」 gain/pulled_days
    accel_warn: bool  # 반영 비율이 accel_warn_ratio 보다 낮음
    next_chain: list[ChainItem]  # 넣은 뒤 약속을 정하는 줄 가운데 묶음이 건드리지 않은 작업(「다음 결정 줄」)
    moves: list[str]  # 바꾸는 것(이동 글)
    violations: int
    uncheckable: int
    recommended: bool
    note: str  # LLM 설명(날짜가 들었거나 실패면 "")


class ShortenOut(BaseModel):
    kind: Literal["shorten_options"] = "shorten_options"
    schedule_id: int
    base: str  # "current" | "s:<지연 반영안 id>"
    base_finish: str
    target: int
    options: list[OptionOut]
    recommended_scenario_id: int


class _Note(BaseModel):
    key: Literal["A", "B", "C"]
    note: str


class _Advice(BaseModel):
    recommended: Literal["A", "B", "C"] | None
    notes: list[_Note]


@dataclass(frozen=True)
class _Base:
    ref: str  # "current" | "s:<지연 반영안 id>"
    schedule: Schedule  # 저장 모양(조건을 넣지 않음)
    conditions: list[dict]
    event_ids: list[int]


def _author(ctx: ToolContext) -> str:
    return ctx.user.name if ctx.user else approvals.AGENT_NAME


def _same_delay(row: Scenario, db, snapshot: dict) -> bool:
    """같은 버전·같은 사건 묶음이고 스냅숏·조건까지 같은 지연 반영안인가(사건 일수를 고치면 id 는 같아도 다르다)."""
    return (row.source == "delay" and row.base_version == db.version
            and sorted(row.delay_event_ids) == sorted(db.event_ids)
            and row.snapshot_json == snapshot and row.conditions_json == db.conditions)


def _delay_scenario(ctx: ToolContext, schedule_id: int, db) -> Scenario:
    """지금 사건을 그대로 넣은 열린 지연 반영안. 없으면 만든다(이름은 지연 화면과 같게)."""
    snapshot = to_json(db.schedule)
    for row in scenarios.listed(ctx.session, schedule_id, ("open",)):
        if _same_delay(row, db, snapshot):
            return row
    return scenarios.create(ctx.session, schedule_id=schedule_id, base_version=db.version,
                            name=DELAY_NAME.format(len(db.event_ids)),
                            source="delay", schedule=db.schedule, conditions=db.conditions,
                            delay_event_ids=db.event_ids, created_by=_author(ctx))


def _discard_older(ctx: ToolContext, schedule_id: int, n: int) -> None:
    """옛 버전 기준의 열린 만회안·지연 반영안을 버린다(비교판·보고서에 같은 이름의 옛 안이 섞이지 않게). flush 만."""
    for row in scenarios.listed(ctx.session, schedule_id, ("open",)):
        if row.source in ("shorten", "delay") and row.base_version < n:
            scenarios.set_status(ctx.session, row, "discarded")


def _base(ctx: ToolContext, schedule_id: int, current: Schedule, stored: list[dict], include_open_delays: bool) -> _Base:
    if include_open_delays:
        db = delayed_base(ctx.session, schedule_id)
        if db.event_ids:
            row = _delay_scenario(ctx, schedule_id, db)
            return _Base(f"s:{row.id}", db.schedule, db.conditions, db.event_ids)
    return _Base("current", current, stored, [])


def _target(ctx: ToolContext, schedule_id: int, args: ShortenIn, base: _Base, ready: Schedule, base_finish: date) -> int:
    """줄일 근무일: target_days → 가장 이른 켜진 기한 → Plan 준공. 없으면 ToolError."""
    if args.target_days is not None:
        return args.target_days
    cal = WorkCalendar(ready.calendar)
    assembled = assemble_all(read_conditions(base.conditions)[0])
    dues = [date.fromisoformat(c.params["date"]) for c in assembled
            if condition_problem(c) is None and c.enabled and c.kind == "finish_by"]
    if dues and base_finish > min(dues):
        return cal.workdays_between(min(dues), base_finish)
    current, stored, n = load(ctx.session, schedule_id)
    plan = plan_of(ctx.session, schedule_id, n, run(current, stored))
    if plan is not None and base_finish > plan.finish:
        return cal.workdays_between(plan.finish, base_finish)
    raise ToolError(NO_TARGET_MESSAGE)


def _with_caps(conditions: list[dict], schedule: Schedule, moves: tuple[Move, ...]) -> list[dict]:
    """자원 추가 이동마다 입력 조건 in.resource_cap.<자원>. 같은 id 의 조건은 빼고 뒤에 붙인다(입력 겹에서 이기게)."""
    resources = {r.id: r for r in schedule.resources}
    caps = []
    for m in moves:
        if m.kind == "add_resource":
            r = resources[m.resource_id]
            params = {"resource_id": r.id, "capacity": m.capacity}
            caps.append(Condition(f"in.resource_cap.{r.id}", "input", "resource_cap", params,
                                  f"{r.name} {m.capacity}{r.unit}", CONDITION_SOURCE).to_dict())
    ids = {c["id"] for c in caps}
    return [c for c in conditions if not (isinstance(c, dict) and c.get("id") in ids)] + caps


def _accel(ctx: ToolContext, ready: Schedule, p: Package) -> dict:
    """묶음의 당김 효과(요약 칸). 준공 반영 일수는 gain 과 같은 셈이다."""
    cfg = points_config(ctx.session)
    r = accel_effect(ready, p.moves, warn_ratio=accel_warn_ratio(ctx.session), tf_days=cfg.tf_days,
                     window_weeks=cfg.window_weeks)
    return {"pulled_days": r.pulled_days, "accel_warn": r.warn, "next_chain": chain_items(ready, r)}


def _copies(
    ctx: ToolContext, schedule_id: int, n: int, base: _Base, ready: Schedule, result: ShortenResult
) -> list[tuple[Package, Scenario]]:
    """이동이 있는 묶음마다 복사본(source shorten)."""
    out = []
    for p in result.packages:
        if not p.moves:
            continue
        row = scenarios.create(
            ctx.session, schedule_id=schedule_id, base_version=n, name=f"만회안 {p.key} · {p.name}", source="shorten",
            schedule=apply_moves(base.schedule, p.moves, resources=False),
            conditions=_with_caps(base.conditions, base.schedule, p.moves), moves=p.moves,
            delay_event_ids=base.event_ids, created_by=_author(ctx),
            extra_summary={"gain": p.gain, "base_finish": result.base_finish.isoformat(), "note": "",
                           "recommended": False, **_accel(ctx, ready, p)},
        )
        out.append((p, row))
    return out


def _option(p: Package, row: Scenario) -> dict:
    s = row.summary_json
    return {"scenario_id": row.id, "key": p.key, "name": row.name, "finish": s["finish"], "gain": p.gain,
            "reached": p.reached, "pulled_days": s["pulled_days"], "accel_warn": s["accel_warn"],
            "next_chain": s["next_chain"], "moves": [m.text for m in p.moves], "violations": len(s["violations"]),
            "uncheckable": s["uncheckable"], "recommended": False, "note": ""}


async def _advice(ctx: ToolContext, options: list[dict]) -> tuple[str | None, dict[str, str]]:
    """(LLM 추천 key 또는 None, key → 설명). 실패·잘린 답·모양 틀림은 (None, {})."""
    shown = [{k: o[k] for k in ("key", "name", "finish", "gain", "reached", "moves", "violations")} for o in options]
    messages = [{"role": "system", "content": NOTE_PROMPT.read_text(encoding="utf-8")},
                {"role": "user", "content": json.dumps(shown, ensure_ascii=False)}]
    try:
        reply = await client_for(ctx).chat("hard", messages, json_schema=SHORTEN_NOTE_SCHEMA,
                                           chat_session_id=ctx.chat_session_id)
        if reply.finish_reason == "length":  # 잘린 답은 모양이 맞아도 쓰지 않는다
            return None, {}
        advice = _Advice.model_validate(reply.parsed)
    except (LlmNotReady, LlmFailed, ValidationError):
        return None, {}
    keys = {o["key"] for o in options}
    notes: dict[str, str] = {}
    for item in advice.notes:
        if item.key in keys and item.key not in notes:
            notes[item.key] = "" if DATE_IN_TEXT.search(item.note) else item.note.strip()
    return (advice.recommended if advice.recommended in keys else None), notes


def code_pick(options: list[dict]) -> str:
    """코드 추천: 도달한 것 → 위반 적은 것 → 이동 적은 것 → 이득 큰 것 → key 순."""
    return min(options, key=lambda o: (not o["reached"], o["violations"], len(o["moves"]), -o["gain"], o["key"]))["key"]


async def _recommend(ctx: ToolContext, made: list[tuple[Package, Scenario]], options: list[dict]) -> int:
    """설명·추천을 정해 안과 복사본 요약에 넣는다(flush). 추천 복사본 id."""
    chosen, notes = await _advice(ctx, options)
    chosen = chosen or code_pick(options)
    for o, (_, row) in zip(options, made, strict=True):
        o["recommended"], o["note"] = o["key"] == chosen, notes.get(o["key"], "")
        row.summary_json = {**row.summary_json, "note": o["note"], "recommended": o["recommended"]}
    ctx.session.flush()
    return next(o["scenario_id"] for o in options if o["recommended"])


@tool(
    "shorten.make",
    "만회·단축안을 만든다: {target_days?(당길 근무일, 사용자가 말했을 때만), include_open_delays(기본 true)}. "
    "목표를 주지 않으면 가장 이른 준공 기한, 없으면 Plan 준공까지 당긴다. 병행·압축·자원 추가 묶음마다 복사본을 만들고 "
    "준공·이득·위반은 코드가 계산한다. 비교판이 열린다. 일정은 바뀌지 않는다(반영은 scenario__submit).",
    program="compare",
    mutates=True,
)
async def make_shortening(args: ShortenIn, ctx: ToolContext) -> ShortenOut:
    schedule_id = ctx.require_schedule_id()
    with explained_schedule_errors():
        current, stored, n = load(ctx.session, schedule_id)
        _discard_older(ctx, schedule_id, n)
        base = _base(ctx, schedule_id, current, stored, args.include_open_delays)
        ready = prepare_stored(base.schedule, base.conditions)
        base_finish = level(ready, compute(ready)).finish
        target = _target(ctx, schedule_id, args, base, ready, base_finish)
        result = shorten(ready, target=target)
        made = _copies(ctx, schedule_id, n, base, ready, result)
    if not made:
        raise ToolError(NOTHING_MESSAGE)
    options = [_option(p, row) for p, row in made]
    ctx.session.commit()  # LLM 을 부르기 전에 쓰기를 끝낸다
    recommended = await _recommend(ctx, made, options)
    out = ShortenOut(schedule_id=schedule_id, base=base.ref, base_finish=result.base_finish.isoformat(), target=target,
                     options=options, recommended_scenario_id=recommended)
    ctx.emit(AgentEvent("card", out.model_dump(mode="json")))
    ctx.emit(AgentEvent("open_window", {"program": "compare", "params": {
        "id": str(schedule_id), "base": base.ref, "other": f"s:{recommended}"}}))
    return out
