"""도구 field.list(A6-3): 대상 일정의 현장 점검 목록(체크인·사진 판독·만회안 의견·D-3 핸드오프)과 요약 집계를 읽는다.

화면의 GET /api/schedules/{id}/field 와 같은 서비스(programs.progress.field.list_field)라 그 일정의 항목만 본다.
결과는 짧게: 항목 수·글 길이에 한도가 있고 사진 원본(data URL)은 넣지 않는다. 자료는 모두 가상(5층 사무동 신축).
"""

import json
from dataclasses import replace

from app.agent.context import RESULT_LIMIT
from app.store.tables import FieldItem
from app.tools.data import list_field
from app.tools.registry import call, list_tools
from tests import schedules

NOTE = "후행 자재 창고 입고 대기(내일 오전 반입 예정)"


def handoff(sid: int, **over) -> FieldItem:
    return FieldItem(**{
        "schedule_id": sid, "kind": "handoff", "activity_id": "B", "activity_name": "작업 B",
        "trade": "골조팀 → 설비팀", "status": "responded", "title": "[D-3 핸드오프] A → B",
        "response_choice": "hold", "response_note": NOTE,
        "payload_json": {"pred_id": "A", "days_left": 3, "pred_handover_ok": True,
                         "checklist": {"material": False, "equipment": True, "workforce": True}},
        **over,
    })


def checkin(sid: int, **over) -> FieldItem:
    return FieldItem(**{
        "schedule_id": sid, "kind": "checkin", "activity_id": "A", "activity_name": "작업 A", "trade": "골조팀 박반장",
        "status": "pending", "title": "[체크인 요청] A 작업 A", **over,
    })


def stored(session, *items) -> int:
    sid = schedules.store(session, schedules.sample())
    session.add_all(item(sid) for item in items)
    session.commit()
    return sid


def test_field_list_is_a_read_tool_of_the_progress_program():
    spec = {t.name: t for t in list_tools()}["field.list"]
    assert (spec.program, spec.mutates) == ("progress", False) and spec.description


async def test_handoff_shows_the_material_not_ready_and_its_note(session, ctx):
    sid = stored(session, checkin, handoff)
    r = await call("field.list", {"kind": "handoff"}, replace(ctx, schedule_id=sid))
    assert r.ok, r.error
    out = r.output
    assert (out["schedule_id"], out["total"]) == (sid, 1)
    [item] = out["items"]
    assert (item["kind"], item["activity_id"], item["status"], item["response_choice"]) == ("handoff", "B", "responded", "hold")
    assert item["response_note"] == NOTE
    assert item["payload_json"]["checklist"] == {"material": False, "equipment": True, "workforce": True}
    assert out["summary"]["handoff_total"] == 1 and out["summary"]["checkin_total"] == 1  # 집계는 거르기 전 전체


async def test_filters_by_status_and_reads_the_given_schedule(session, ctx):
    sid = stored(session, checkin, handoff)
    r = await call("field.list", {"schedule_id": sid, "status": "pending"}, ctx)  # 문맥에 일정이 없어도 id 로
    assert r.ok, r.error
    assert [i["kind"] for i in r.output["items"]] == ["checkin"] and r.output["total"] == 1


async def test_only_that_schedules_items_are_seen(session, ctx):
    mine = stored(session, handoff)
    other = stored(session, checkin, lambda sid: checkin(sid, title="[체크인 요청] 다른 현장"))
    r = await call("field.list", {}, replace(ctx, schedule_id=mine))
    assert r.ok, r.error
    assert {i["id"] for i in r.output["items"]} == {
        i.id for i in session.query(FieldItem).filter(FieldItem.schedule_id == mine)}
    assert all(i["kind"] == "handoff" for i in r.output["items"])
    assert r.output["summary"]["checkin_total"] == 0  # 다른 일정의 체크인은 세지 않는다
    theirs = await call("field.list", {}, replace(ctx, schedule_id=other))
    assert theirs.output["total"] == 2 and theirs.output["summary"]["handoff_total"] == 0


async def test_no_target_or_unknown_schedule_is_refused_in_korean(ctx):
    none = await call("field.list", {}, ctx)
    missing = await call("field.list", {"schedule_id": 999}, ctx)
    bad = await call("field.list", {"kind": "survey"}, ctx)
    assert (none.ok, none.error) == (False, "대상 일정이 없습니다.")
    assert (missing.ok, missing.error) == (False, "일정을 찾을 수 없습니다.")
    assert not bad.ok and bad.error.startswith("입력 형식 오류: kind")


async def test_output_is_bounded_and_leaves_out_photo_data(session, ctx):
    long = "가" * 1000
    photo = {"photo_name": "사진" * 200, "photo_data_url": "data:image/png;base64," + "A" * 300_000,
             "ai_risks": [long] * 10, "confidence": 0.9}
    makers = [lambda sid, n=n: FieldItem(
        schedule_id=sid, kind="photo", activity_id="A", activity_name=long, trade=long, status="responded",
        title=f"{n:02} {long}", response_choice="risk", response_note=long, payload_json=photo) for n in range(30)]
    sid = stored(session, *makers)
    r = await call("field.list", {}, replace(ctx, schedule_id=sid))
    assert r.ok, r.error
    out = r.output
    assert out["total"] == 30 and len(out["items"]) == list_field.ITEM_LIMIT
    assert out["items"][0]["title"].startswith("29 ")  # 최근 것부터
    for item in out["items"]:
        assert "photo_data_url" not in item["payload_json"]
        assert len(item["payload_json"]["ai_risks"]) <= list_field.LIST_LIMIT
        for text in (item["title"], item["activity_name"], item["trade"], item["response_note"],
                     item["payload_json"]["photo_name"], *item["payload_json"]["ai_risks"]):
            assert len(text) <= list_field.TEXT_LIMIT
    assert len(json.dumps(out, ensure_ascii=False)) <= RESULT_LIMIT  # 도구 결과 한도 안에(잘리지 않는다)
