"""개발 콘솔 하네스: 11-23 에 더한 코드 강제 규칙의 실엔진 차단 시험(live_harness).

시험마다 (1) 진짜 함수를 대본 입력으로 돌려 막았음(blocked)과 관측값을 확인하고, (2) 그 막는 코드를 일부러
빼면(monkeypatch) 같은 시험이 「차단 안 됨」으로 바뀌는지 본다. 네트워크·LLM 은 쓰지 않고 운영 DB 에는 남지 않는다.
"""

import json
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.agent import generation, loop
from app.info import generic
from app.programs.devconsole import harness_live
from app.programs.progress import field
from app.store import evidence_reuse
from app.store.tables import (
    EvidenceItem,
    EvidenceSearch,
    FieldItem,
    LlmCall,
    ScheduleDraft,
    ScheduleRecord,
    User,
)
from app.tools.context import ToolContext
from app.tools.data import info_call
from app.tools.generate import extract_conditions

NEW_RULES = ["H-INFO-01", "H-INFO-02", "H-INFO-03", "H-EVR-01", "H-ROLE-01", "H-IMP-01", "H-GEN-01", "H-FLD-01",
             "H-DATE-01"]
GROUPS = {"일정 계산", "에이전트 루프", "외부 정보", "권한", "가져오기·생성", "현장"}


def harness_test(client, admin, rule_id: str) -> dict:
    r = client.post(f"/api/devconsole/harness/{rule_id}/test", headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["engine"] == "live_harness" and body["rule_id"] == rule_id
    return body


def live_rows(session) -> dict[str, int]:
    session.expire_all()
    tables = (EvidenceSearch, EvidenceItem, LlmCall, ScheduleDraft, ScheduleRecord, FieldItem)
    return {t.__tablename__: session.scalar(select(func.count()).select_from(t)) for t in tables} | {
        "users": session.scalar(select(func.count()).select_from(User))}


def test_catalog_lists_the_new_rules_grouped(client, admin):
    rules = client.get("/api/devconsole/catalog", headers=admin).json()["harness"]
    ids = [r["id"] for r in rules]
    assert all(rid in ids for rid in NEW_RULES)
    assert {r["group"] for r in rules} <= GROUPS and all(r["group"] for r in rules)
    by_id = {r["id"]: r for r in rules}
    assert by_id["H-CPM-01"]["group"] == "일정 계산" and by_id["H-LOOP-01"]["group"] == "에이전트 루프"
    assert by_id["H-INFO-02"]["group"] == "외부 정보" and by_id["H-ROLE-01"]["group"] == "권한"
    assert by_id["H-FLD-01"]["group"] == "현장" and by_id["H-GEN-01"]["group"] == "가져오기·생성"
    # 세션 기록이 없는 규칙은 수를 지어내지 않는다(null)
    assert by_id["H-DATE-01"]["passed_count"] is None and by_id["H-DATE-01"]["blocked_count"] is None


def test_every_new_rule_runs_in_a_throwaway_db_and_holds(client, admin, session):
    before = live_rows(session)
    for rule_id in NEW_RULES:
        body = harness_test(client, admin, rule_id)
        assert body["blocked"] is True, f"{rule_id}: {body['model_feedback']}"
    assert live_rows(session) == before  # 운영 DB 에는 아무것도 남지 않는다


# ── 외부 정보 ───────────────────────────────────────────────────────


def test_info_path_guard_refuses_paths_that_leave_the_connection(client, admin):
    fb = harness_test(client, admin, "H-INFO-01")["model_feedback"]
    assert all(not r["ok"] and r["error"] for r in fb["refused"]) and len(fb["refused"]) >= 4
    assert fb["requests_for_refused"] == 0 and fb["control"]["ok"] is True and fb["counted"] == 1


def test_info_path_guard_fails_when_the_guard_is_removed(client, admin, monkeypatch):
    monkeypatch.setattr(generic, "request_problem", lambda path, params, key_name: None)
    monkeypatch.setattr(generic, "_on_base", lambda url, base: True)
    body = harness_test(client, admin, "H-INFO-01")
    assert body["blocked"] is False


def test_info_key_planted_in_a_response_never_reaches_the_tool_result(client, admin):
    fb = harness_test(client, admin, "H-INFO-02")["model_feedback"]
    assert fb["key_sent_to_server"] is True and fb["planted_forms"] >= 3
    assert fb["key_in_tool_result"] is False and fb["key_in_saved_evidence"] is False and fb["masked"] >= 1


def test_info_key_harness_fails_when_responses_are_not_scrubbed(client, admin, monkeypatch):
    monkeypatch.setattr(generic, "_clean", lambda text, conn, dropped: text)
    body = harness_test(client, admin, "H-INFO-02")
    assert body["blocked"] is False and body["model_feedback"]["key_in_tool_result"] is True


def test_info_limit_allows_four_calls_then_refuses(client, admin):
    fb = harness_test(client, admin, "H-INFO-03")["model_feedback"]
    assert fb["results"] == ["ok", "ok", "ok", "ok", "refused"] and fb["requests"] == 4
    assert fb["fifth_error"] == info_call.LIMIT_MESSAGE and fb["limit"] == 4


def test_info_limit_harness_fails_when_the_limit_is_lifted(client, admin, monkeypatch):
    monkeypatch.setattr(info_call, "LIMIT", 99)
    assert harness_test(client, admin, "H-INFO-03")["blocked"] is False


def test_evidence_reuse_only_reuses_linked_recent_live_evidence_and_fresh_bypasses(client, admin):
    fb = harness_test(client, admin, "H-EVR-01")["model_feedback"]
    assert fb["found"] == ["붙음·1일·살아 있음"]
    assert set(fb["not_found"]) == {"붙은 곳 없음", "31일 지남", "다시 쓰지 않기"}
    assert fb["tool_reused"] is True and fb["tool_results"] == ["붙음·1일·살아 있음"]
    assert fb["fresh_reused"] is False and fb["fresh_tried_liner"] is True


def test_evidence_reuse_harness_fails_when_the_age_limit_is_lifted(client, admin, monkeypatch):
    monkeypatch.setattr(evidence_reuse, "REUSE_DAYS", 365)
    body = harness_test(client, admin, "H-EVR-01")
    assert body["blocked"] is False and "31일 지남" in body["model_feedback"]["found"]


# ── 권한 ────────────────────────────────────────────────────────────


def test_role_rule_refuses_the_field_role_on_an_edit_tool_and_route_but_not_the_user_role(client, admin):
    fb = harness_test(client, admin, "H-ROLE-01")["model_feedback"]
    assert fb["field_tool"] == {"ok": False, "error": "현장 관리자는 일정을 고치거나 승인·거부할 수 없습니다."}
    assert fb["user_tool"]["ok"] is True
    assert fb["route"] == "PATCH /api/schedules/{schedule_id}" and fb["route_has_guard"] is True
    assert fb["field_route"] == {"status": 403, "code": "field_read_only"} and fb["user_route"] == "통과"


def test_role_harness_fails_when_the_tool_check_is_removed(client, admin, monkeypatch):
    monkeypatch.setattr(ToolContext, "require_editor", lambda self: None)
    body = harness_test(client, admin, "H-ROLE-01")
    assert body["blocked"] is False and body["model_feedback"]["field_tool"]["ok"] is True


# ── 가져오기·생성 ───────────────────────────────────────────────────


def test_import_button_fills_confirmed_only_for_the_fixed_sentence_and_a_repeat_is_refused(client, admin, session):
    fb = harness_test(client, admin, "H-IMP-01")["model_feedback"]
    assert fb["button_turn_confirmed"] is True and fb["other_text_confirmed"] is False
    assert fb["second_check"] == loop.CHECK_AGAIN.format("7")
    assert fb["second_import"] == loop.IMPORT_AGAIN.format("7")
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(LlmCall)) == 0


def test_import_harness_fails_when_any_text_fills_confirmed(client, admin, monkeypatch):
    import re

    monkeypatch.setattr(loop, "IMPORT_BUTTON", re.compile(r".*#(\d+).*"))  # 파일 번호만 있으면 아무 글이나
    body = harness_test(client, admin, "H-IMP-01")
    assert body["blocked"] is False and body["model_feedback"]["other_text_confirmed"] is True


def test_repair_loop_stops_on_the_same_violations_and_keeps_the_best_draft(client, admin):
    fb = harness_test(client, admin, "H-GEN-01")["model_feedback"]
    assert fb["rounds"] == [1, 1] and fb["llm_requests"] == 3
    assert fb["reason"] == generation.REPEAT_REASON and fb["draft_saved"] is True and fb["conflict"] == ["in.finish_by"]


def test_repair_harness_fails_when_the_repeat_check_is_removed(client, admin, monkeypatch):
    monkeypatch.setattr(generation._Loop, "same_as_before", lambda self, scored: False)
    body = harness_test(client, admin, "H-GEN-01")
    assert body["blocked"] is False and body["model_feedback"]["rounds"] != [1, 1]


# ── 현장 · 일정 계산 ─────────────────────────────────────────────────


def test_photo_reading_makes_no_percentage_without_a_model_answer(client, admin):
    fb = harness_test(client, admin, "H-FLD-01")["model_feedback"]
    assert [c["reported_progress"] for c in fb["cases"]] == [None, None]
    assert [c["response_choice"] for c in fb["cases"]] == ["unread", "unread"]
    assert fb["cases"][0]["why"] == field.NO_PHOTO and fb["cases"][1]["why"].startswith("판독하지 못했습니다")


def test_photo_harness_fails_when_a_number_is_made_up(client, admin, monkeypatch):
    async def made_up(session, act, data_url, note):
        return field.VisionAnswer(readable=True, progress=95, reason="완료", risks=[]), None

    monkeypatch.setattr(field, "_read_photo", made_up)
    body = harness_test(client, admin, "H-FLD-01")
    assert body["blocked"] is False and body["model_feedback"]["cases"][1]["reported_progress"] == 95


def test_weeks_after_start_deadline_becomes_a_date(client, admin):
    fb = harness_test(client, admin, "H-DATE-01")["model_feedback"]
    assert (fb["start"], fb["after_start"], fb["finish_by"]) == ("2027-06-07", "16주", "2027-09-26")


def test_deadline_harness_fails_when_the_last_day_is_not_subtracted(client, admin, monkeypatch):
    monkeypatch.setattr(extract_conditions, "_after", lambda start, amount, unit: start + timedelta(days=7 * amount))
    body = harness_test(client, admin, "H-DATE-01")
    assert body["blocked"] is False and body["model_feedback"]["finish_by"] == "2027-09-27"


# ── 세션 기록(수는 기록에서만) ──────────────────────────────────────


def test_session_counts_come_from_recorded_steps(client, admin, session):
    from tests.programs.test_devconsole_api import made_turn

    made_turn(session, events=[], steps=[
        {"tool": "info.call", "status": "failed", "output_json": json.dumps({"error": info_call.LIMIT_MESSAGE}, ensure_ascii=False)},
        {"tool": "info.call"},
        {"tool": "out.submit_change", "status": "failed",
         "output_json": '{"error": "현장 관리자는 일정을 고치거나 승인·거부할 수 없습니다."}'},
    ])
    rules = {r["id"]: r for r in client.get("/api/devconsole/catalog", headers=admin).json()["harness"]}
    assert (rules["H-INFO-03"]["passed_count"], rules["H-INFO-03"]["blocked_count"]) == (1, 1)
    assert rules["H-ROLE-01"]["blocked_count"] == 1


@pytest.mark.parametrize("rule_id", ["H-NOPE-01"])
def test_unknown_rule_is_404(client, admin, rule_id):
    assert client.post(f"/api/devconsole/harness/{rule_id}/test", headers=admin).status_code == 404


def test_harness_module_lists_only_rules_it_can_run():
    assert set(harness_live.RUNNERS) == {r["id"] for r in harness_live.RULES}
