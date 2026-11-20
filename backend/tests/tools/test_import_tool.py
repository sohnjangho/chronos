"""도구 schedule.import: 공정표 파일을 확인(요약 카드)하고, 물어보거나 추정해 일정 초안으로 가져와 승인함에 낸다(Task 53).

판단(공정표인가·열 대응·빈 칸을 물을지·파일 날짜를 제약으로 둘지)은 가짜 LLM(ScriptedLlm) 대본이고,
행 수·빈 칸·기간·선행·날짜 계산은 코드다. 자료는 모두 가상(5층 사무동 신축).
"""

import hashlib
import io
import json
from datetime import date, datetime, timedelta

import pytest
from openpyxl import Workbook
from sqlalchemy import select

import app.tools.generate as generate_tools
from app.llm.client import MAX_TOKENS, LlmClient
from app.store.drafts import get_draft
from app.store.files import raw_path
from app.store.schedules import from_json, run
from app.store.tables import Approval, FileRow, QuestionnaireRecord, ScheduleDraft, User
from app.tools.registry import call, list_tools
from tests.gen_doubles import reply, user_text
from tests.llm_doubles import add_connection
from tests.loop_doubles import ScriptedLlm

HEADER = ["작업 ID", "작업명", "WBS", "선행 작업", "시작일", "종료일", "비고"]
FIRST = date(2027, 3, 2)
BIG_IDS = [f"A{1000 + 10 * i}" for i in range(120)]

# 선행이 있는 작은 공정표. B·D 는 기간이 비었다. C 는 A 시작 2일 뒤 시작(SS+2).
PRED_CSV = (
    "ID,작업,기간,선행,시작,종료\n"
    "S,착공,0,,2027-03-02,\n"
    "A,가설 울타리,5,S,2027-03-02,2027-03-06\n"
    "B,터파기,,A,,2027-03-12\n"
    "C,기초 거푸집,3,A SS+2,,\n"
    'D,지하 방수,,"B, C",,\n'
    "F,준공,0,D,,\n"
)
COMPLETE_CSV = PRED_CSV.replace("B,터파기,,A", "B,터파기,4,A").replace('D,지하 방수,,"B', 'D,지하 방수,2,"B')
MATERIALS_CSV = "품명,규격,수량,단가\n레미콘,25-24-150,120,85000\n철근,HD13,30,950000\n"
QUESTIONS = [
    {
        "id": f"q{i}", "group": "기간", "question": f"공종 묶음 {i}의 기간 기준은?", "why": "기간 열이 비어 있습니다.",
        "options": [{"value": "base", "label": "분야 기준값", "hint": None, "recommended": True},
                    {"value": "fix", "label": "표를 고쳐 다시 올림", "hint": None, "recommended": False}],
        "allow_free": True, "assumption": "분야 기준값으로 추정합니다.",
    }
    for i in range(1, 4)
]


@pytest.fixture
def llm() -> ScriptedLlm:
    return ScriptedLlm()


@pytest.fixture(autouse=True)
def fake_llm(session, llm, monkeypatch):
    """도구가 쓰는 LLM 을 대본 LLM 으로 바꾼다(기본 연결 하나)."""
    add_connection(session)
    monkeypatch.setattr(generate_tools, "client_for", lambda ctx: LlmClient(ctx.session, transport=llm.transport))


def put(session, data: bytes, name: str, kind: str) -> int:
    """파일 한 줄과 원본(data/files/…)을 바로 넣는다(뒤 작업 줄 없이)."""
    sha = hashlib.sha256(data).hexdigest()
    path = raw_path(sha)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    admin = session.scalars(select(User).where(User.login_id == "admin")).one()
    row = FileRow(sha256=sha, name=name, ext=name.rsplit(".", 1)[-1], kind=kind, size=len(data),
                  status="extracted", uploaded_by=admin.id)
    session.add(row)
    session.commit()
    return row.id


def big_xlsx() -> bytes:
    """기간 열이 없는 가상 공정표 120행(시트 「공정표」) + 시트 「메모」."""
    wb = Workbook()
    ws = wb.active
    ws.title = "공정표"
    ws.append(HEADER)
    for i, aid in enumerate(BIG_IDS):
        start = datetime.combine(FIRST + timedelta(days=i), datetime.min.time())
        pred = BIG_IDS[i - 1] if i else None
        ws.append([aid, f"5층 사무동 공종 {i + 1}", f"1.{i // 30 + 1}", pred, start, start + timedelta(days=1), None])
    wb.create_sheet("메모").append(["가상 현장 메모"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def plan(**over) -> dict:
    """열 대응·빈 칸·날짜 판단(큰 엑셀의 열 이름)."""
    return reply({
        "id_col": "작업 ID", "name_col": "작업명", "wbs_col": "WBS", "duration_col": None, "pred_col": "선행 작업",
        "start_col": "시작일", "finish_col": "종료일", "blanks": "estimate", "questions": [],
        "start_constraint": False, "finish_constraint": False, "reason": "기간 열이 없어 분야 기준값으로 추정합니다.",
        **over,
    })


def csv_plan(**over) -> dict:
    return plan(**{"id_col": "ID", "name_col": "작업", "wbs_col": None, "duration_col": "기간", "pred_col": "선행",
                   "start_col": "시작", "finish_col": "종료", **over})


def est(aid: str, od: int, kind: str = "task", **extra) -> dict:
    """LLM 이 빈 칸을 채운 액티비티 한 줄(이름·WBS 는 코드가 파일 값으로 덮는다)."""
    return {"id": aid, "name": "", "kind": kind, "wbs": "", "od": od, "tags": [], "predecessors": [], **extra}


def estimate(*acts: dict) -> dict:
    return reply({"activities": list(acts)})


def importing(fid: int, **over) -> dict:
    return {"file_id": fid, "confirmed": True, "domain": "construction", "level": "L2", **over}


def test_import_tool_is_registered():
    spec = {t.name: t for t in list_tools()}["schedule.import"]
    assert spec.mutates and spec.description  # 초안·승인 건을 저장한다


async def test_detect_card_counts_rows_by_code(ctx, events, llm, session):
    fid = put(session, big_xlsx(), "사무동_공정표.xlsx", "sheet")
    # LLM 이 숫자를 내도(rows 999) 카드의 숫자는 코드가 센다
    llm.push(reply({"is_schedule": True, "reason": "작업명·선행·시작·종료 열이 있습니다.", "rows": 999}), plan())
    r = await call("schedule.import", {"file_id": fid}, ctx)
    assert r.ok, r.error
    cards = [e.data for e in events if e.type == "card"]
    assert cards == [{
        "kind": "schedule_file", "file_id": fid, "sheet": "공정표", "rows": 120,
        "columns_found": ["작업 ID", "작업명", "WBS", "선행 작업", "시작일", "종료일"], "missing": ["기간"],
    }]
    out = r.output
    assert (out["step"], out["is_schedule"], out["rows"], out["sheets"]) == ("checked", True, 120, ["공정표", "메모"])
    assert [b["max_tokens"] for b in llm.bodies] == [MAX_TOKENS["normal"]] * 2  # 판단은 normal
    assert all(b["response_format"]["json_schema"]["strict"] for b in llm.bodies)
    assert session.scalars(select(ScheduleDraft)).all() == []  # 확인만 — 먼저 묻고 가져온다


async def test_non_schedule_table_gets_no_card(ctx, events, llm, session):
    fid = put(session, MATERIALS_CSV.encode(), "자재_목록.csv", "table")
    llm.push(reply({"is_schedule": False, "reason": "자재 수량·단가 표입니다."}))
    r = await call("schedule.import", {"file_id": fid}, ctx)
    assert r.ok, r.error
    assert [e for e in events if e.type == "card"] == []
    out = r.output
    assert (out["step"], out["is_schedule"], out["reason"], out["rows"]) == ("checked", False, "자재 수량·단가 표입니다.", 2)
    assert len(llm.bodies) == 1  # 공정표가 아니면 열 대응을 묻지 않는다


async def test_import_keeps_file_values_and_marks_estimates(ctx, llm, session):
    fid = put(session, PRED_CSV.encode(), "기초_공정.csv", "table")
    llm.push(csv_plan(), estimate(
        est("A", 99, predecessors=[{"pred": "S", "type": "FF", "lag": 9}]),  # 파일 값이 있는 칸 — 덮인다
        est("B", 4), est("D", 2),
        est("X", 3),  # 파일에 없는 액티비티 — 버린다
    ))
    r = await call("schedule.import", importing(fid), ctx)
    assert r.ok, r.error
    assert r.output["step"] == "drafted"
    draft = get_draft(session, r.output["draft"]["draft_id"])
    s = from_json(draft.schedule_json)
    assert [(a.id, a.name, a.kind, a.od) for a in s.activities] == [
        ("S", "착공", "start_ms", 0), ("A", "가설 울타리", "task", 5), ("B", "터파기", "task", 4),
        ("C", "기초 거푸집", "task", 3), ("D", "지하 방수", "task", 2), ("F", "준공", "finish_ms", 0),
    ]
    assert {(x.pred, x.succ, x.type, x.lag) for x in s.relations} == {
        ("S", "A", "FS", 0), ("A", "B", "FS", 0), ("A", "C", "SS", 2), ("B", "D", "FS", 0), ("C", "D", "FS", 0),
        ("D", "F", "FS", 0),
    }
    assert all(a.constraint is None for a in s.activities)  # 에이전트가 날짜 제약을 두지 않았다
    estimated = [(a["label"], a["value"]) for a in draft.assumptions_json if a["source"] == "추정"]
    assert estimated == [("B 터파기", "기간 4일"), ("D 지하 방수", "기간 2일")]
    assert [a["label"] for a in r.output["draft"]["assumptions"] if a["source"] == "추정"] == ["B 터파기", "D 지하 방수"]


async def test_import_asks_when_agent_decides_to(ctx, events, llm, session):
    fid = put(session, big_xlsx(), "사무동_공정표.xlsx", "sheet")
    llm.push(plan(blanks="ask", questions=QUESTIONS))
    r = await call("schedule.import", importing(fid, level="L4"), ctx)
    assert r.ok, r.error
    out = r.output
    assert out["step"] == "asked" and out["questionnaire"]["mode"] == "questionnaire" and out["draft"] is None
    assert [e.type for e in events] == ["questionnaire", "open_window"]  # 기존 질문지 도구 그대로
    record = session.get(QuestionnaireRecord, out["questionnaire"]["id"])
    assert (record.purpose, len(record.questions_json)) == ("generate", 3)
    assert {"label": "액티비티", "value": "120개", "source": "파일"} in record.prefilled_json
    assert len(llm.bodies) == 1  # 추정(생성 루프)은 부르지 않았다
    assert session.scalars(select(ScheduleDraft)).all() == []


async def test_answers_go_to_the_estimate_without_asking_again(ctx, events, llm, session):
    fid = put(session, big_xlsx(), "사무동_공정표.xlsx", "sheet")
    llm.push(plan(blanks="ask", questions=QUESTIONS), estimate(*(est(aid, 3) for aid in BIG_IDS)))
    r = await call("schedule.import", importing(
        fid, level="L4", answers=[{"question": "공종 묶음 1의 기간 기준은?", "answer": "공종마다 3일"}],
        assumed=[{"question": "자재 반입 제약", "assumption": "제약 없음"}],
    ), ctx)
    assert r.ok, r.error
    assert r.output["step"] == "drafted" and r.output["draft"]["activity_count"] == 120
    assert "questionnaire" not in [e.type for e in events]
    text = user_text(llm, 1)
    assert "공종 묶음 1의 기간 기준은?: 공종마다 3일 (질문지)" in text and "자재 반입 제약: 제약 없음 (가정)" in text
    assert "A1010 | 5층 사무동 공종 2 | 1.1 | ? | A1000" in text  # 빈 칸은 '?', 파일 값은 그대로 보인다


async def test_import_goes_to_approvals(ctx, events, llm, session):
    fid = put(session, PRED_CSV.encode(), "기초_공정.csv", "table")
    llm.push(csv_plan(), estimate(est("B", 4), est("D", 2)))
    r = await call("schedule.import", importing(fid), ctx)
    assert r.ok, r.error
    approval = r.output["approval"]
    assert approval["applied"] is False  # 첫 저장은 승인이 필요하다(기본 수준 important)
    row = session.get(Approval, approval["approval_id"])
    assert (row.kind, row.status, row.draft_id) == ("first_save", "pending", r.output["draft"]["draft_id"])
    assert [a["id"] for a in row.snapshot_json["activities"]] == ["S", "A", "B", "C", "D", "F"]
    assert "기초_공정.csv" in row.title
    types = [e.type for e in events]
    assert types[-1] == "approval" and {"kind": "generation_result"}.items() <= events[-2].data.items()


async def test_llm_dates_are_ignored(ctx, llm, session):
    fid = put(session, PRED_CSV.encode(), "기초_공정.csv", "table")
    llm.push(
        csv_plan(start_date="2030-01-01"),  # 모르는 칸 — 버린다
        reply({"start": "2030-01-01", "activities": [
            est("B", 4, es="2030-01-05", start="2030-01-05", finish="2030-01-08"),
            est("D", 2, start="2030-02-01", constraint={"type": "SNET", "date": "2030-02-01"}),
        ]}),
    )
    r = await call("schedule.import", importing(fid), ctx)
    assert r.ok, r.error
    draft = get_draft(session, r.output["draft"]["draft_id"])
    assert draft.schedule_json["start"] == "2027-03-02"  # 파일의 가장 이른 시작일(코드가 고름)
    assert "2030" not in json.dumps(draft.schedule_json)
    cpm = run(from_json(draft.schedule_json), draft.conditions_json)
    assert (cpm.rows["A"].es, cpm.rows["A"].ef) == (date(2027, 3, 2), date(2027, 3, 6))  # 주 6일: 3/2~3/6
    assert r.output["draft"]["finish"] == cpm.finish.isoformat()


async def test_file_dates_become_constraints_when_agent_says_so(ctx, llm, session):
    fid = put(session, PRED_CSV.encode(), "기초_공정.csv", "table")
    llm.push(csv_plan(start_constraint=True, finish_constraint=True), estimate(est("B", 4), est("D", 2)))
    r = await call("schedule.import", importing(fid), ctx)
    assert r.ok, r.error
    draft = get_draft(session, r.output["draft"]["draft_id"])
    got = {a["id"]: a["constraint"] for a in draft.schedule_json["activities"]}
    snet = {"type": "SNET", "date": "2027-03-02"}
    # 한 액티비티에 제약은 하나 — 시작일이 있으면 SNET, 없고 종료일만 있으면 FNLT
    assert got == {"S": snet, "A": snet, "B": {"type": "FNLT", "date": "2027-03-12"}, "C": None, "D": None, "F": None}


async def test_complete_file_needs_no_estimate_call(ctx, llm, session):
    fid = put(session, COMPLETE_CSV.encode(), "기초_공정_완성.csv", "table")
    llm.push(csv_plan())
    r = await call("schedule.import", importing(fid), ctx)
    assert r.ok, r.error
    assert len(llm.bodies) == 1  # 열 대응만 — 빈 칸이 없으니 생성 루프가 LLM 을 부르지 않는다
    out = r.output
    assert out["draft"]["ok"] and out["draft"]["activity_count"] == 6 and out["approval"]["approval_id"]
    assert [a for a in out["draft"]["assumptions"] if a["source"] == "추정"] == []


async def test_a_blank_row_left_out_is_sent_back(ctx, llm, session):
    fid = put(session, PRED_CSV.encode(), "기초_공정.csv", "table")
    llm.push(csv_plan(), estimate(est("B", 4)), estimate(est("B", 4), est("D", 2)))
    r = await call("schedule.import", importing(fid), ctx)
    assert r.ok, r.error
    assert [x["violations"] for x in r.output["draft"]["rounds"]] == [-1, 0]
    assert "답에 없습니다: D" in user_text(llm, 2)  # 같은 고침 루프로 돌려보낸다


async def test_importing_needs_domain_and_level(ctx, llm, session):
    fid = put(session, PRED_CSV.encode(), "기초_공정.csv", "table")
    r = await call("schedule.import", {"file_id": fid, "confirmed": True}, ctx)
    assert not r.ok and "정밀도" in r.error
    assert llm.bodies == []


async def test_unreadable_cells_stop_the_import_with_row_numbers(ctx, llm, session):
    fid = put(session, PRED_CSV.replace("C,기초 거푸집,3", "C,기초 거푸집,2주").encode(), "기초_공정.csv", "table")
    llm.push(csv_plan())
    r = await call("schedule.import", importing(fid), ctx)
    assert not r.ok and "5행 기간 '2주'" in r.error
    assert session.scalars(select(ScheduleDraft)).all() == []
