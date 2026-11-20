"""공정표 가져오기의 코드 쪽(app.files.schedule_import, Task 53): 표 전체 읽기·기간/선행/날짜 읽기·행 → 액티비티.

LLM 은 부르지 않는다(판단은 tests/tools/test_import_tool.py). 자료는 모두 가상.
"""

import hashlib
import io
from datetime import UTC, date, datetime

import pytest
from openpyxl import Workbook

from app.files.schedule_import import (
    ROW_LIMIT,
    ImportProblem,
    Plan,
    convert,
    day,
    duration,
    plan_from,
    predecessors,
    read_table,
)
from app.store.files import raw_path
from app.store.tables import FileRow


def put(session, admin_user, data: bytes, name: str, kind: str, **fields) -> int:
    sha = hashlib.sha256(data).hexdigest()
    path = raw_path(sha)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    row = FileRow(sha256=sha, name=name, ext=name.rsplit(".", 1)[-1], kind=kind, size=len(data),
                  status="extracted", uploaded_by=admin_user.id, **fields)
    session.add(row)
    session.commit()
    return row.id


def csv_bytes(header: str, n: int) -> bytes:
    lines = [header, *(f"A{i},작업 {i},{i % 5 + 1}," for i in range(1, n + 1))]
    return "\n".join(lines).encode()


def two_sheets() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "공정표"
    ws.append(["ID", "작업", "기간"])
    ws.append(["A1", "가설 울타리", 5.0])  # 엑셀 숫자 5.0 은 5
    memo = wb.create_sheet("메모")
    memo.append(["항목", "내용"])
    memo.append(["현장", "5층 사무동 신축(가상)"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_reads_every_row_not_just_the_first_200(session, admin_user):
    fid = put(session, admin_user, csv_bytes("ID,작업,기간,선행", 250), "긴_공정표.csv", "table")
    table = read_table(session, fid, None)
    assert table.header == ["ID", "작업", "기간", "선행"]
    assert len(table.rows) == 250 and table.rows[-1][0] == 251  # (파일 행 번호, 칸) — 머리가 1행
    assert (table.sheet, table.sheets) == (None, [])


def test_more_than_the_row_limit_is_refused_with_guidance(session, admin_user):
    fid = put(session, admin_user, csv_bytes("ID,작업,기간,선행", ROW_LIMIT + 1), "아주_긴_공정표.csv", "table")
    with pytest.raises(ImportProblem, match="2,000"):
        read_table(session, fid, None)


def test_sheet_by_name_and_unknown_sheet(session, admin_user):
    fid = put(session, admin_user, two_sheets(), "공정표.xlsx", "sheet")
    first = read_table(session, fid, None)
    assert (first.sheet, first.sheets, first.rows) == ("공정표", ["공정표", "메모"], [(2, ["A1", "가설 울타리", "5"])])
    assert read_table(session, fid, "메모").header == ["항목", "내용"]
    with pytest.raises(ImportProblem, match=r"없는 시트입니다: 일정 \(시트: 공정표, 메모\)"):
        read_table(session, fid, "일정")


def test_only_readable_table_files(session, admin_user):
    pdf = put(session, admin_user, b"%PDF-1.4 x", "시방서.pdf", "pdf")
    gone = put(session, admin_user, b"ID,x\n1,y\n", "지운.csv", "table", deleted_at=datetime.now(UTC))
    with pytest.raises(ImportProblem, match="표 파일"):
        read_table(session, pdf, None)
    with pytest.raises(ImportProblem, match="지워진 파일입니다"):
        read_table(session, gone, None)
    with pytest.raises(ImportProblem, match="파일을 찾을 수 없습니다"):
        read_table(session, 999, None)


def test_durations_are_whole_workdays():
    assert [duration(t) for t in ["5", "5.0", "5일", "5 일", "5d", "10 days", "0"]] == [5, 5, 5, 5, 5, 10, 0]
    for bad in ["2주", "2.5", "-1", "약 3일", "99999"]:
        with pytest.raises(ValueError):
            duration(bad)


def test_predecessors_follow_the_table_grammar():
    ids = {"A1010", "A1040", "a1", "A1"}
    assert predecessors("A1010, A1040 SS+15", ids) == [
        {"pred": "A1010", "type": "FS", "lag": 0}, {"pred": "A1040", "type": "SS", "lag": 15},
    ]
    assert predecessors("a1 ff-2", ids) == [{"pred": "a1", "type": "FF", "lag": -2}]  # 종류는 소문자도 받는다
    assert predecessors("", ids) == []
    for text, message in [
        ("A1+3", "관계 종류가 빠졌습니다: A1+3 (예: A1 SS+3)"),
        ("Z9", "없는 액티비티입니다: Z9"),
        ("A1 XX", "선행 형식이 맞지 않습니다: A1 XX"),
        ("A1 SS+999", "선행 간격이 너무 큽니다: A1 SS+999"),
    ]:
        with pytest.raises(ValueError, match=message.replace("(", r"\(").replace(")", r"\)").replace("+", r"\+")):
            predecessors(text, ids)


def test_dates_in_common_forms():
    for text in ["2027-03-02", "2027.3.2", "2027/03/02", "2027년 3월 2일", "2027-03-02 00:00:00"]:
        assert day(text) == date(2027, 3, 2)
    for bad in ["3월 2일", "2027-13-01", "내일"]:
        with pytest.raises(ValueError):
            day(bad)


def table_of(session, admin_user, text: str):
    return read_table(session, put(session, admin_user, text.encode(), "공정.csv", "table"), None)


CSV = "ID,작업,WBS,기간,선행\nS,착공,1.1,0,\nA,울타리,1.2.1,5,S\nB,터파기,,,A\n"
PLAN = Plan(id_col="ID", name_col="작업", wbs_col="WBS", duration_col="기간", pred_col="선행")


def test_convert_keeps_file_values_and_marks_blanks(session, admin_user):
    rows = convert(table_of(session, admin_user, CSV), PLAN)
    got = [(r.line, r.id, r.name, r.wbs, r.od, r.preds) for r in rows.rows]
    assert got == [
        (2, "S", "착공", "1.1", 0, ()),
        (3, "A", "울타리", "1.2.1", 5, ({"pred": "S", "type": "FS", "lag": 0},)),
        (4, "B", "터파기", "0", None, ({"pred": "A", "type": "FS", "lag": 0},)),  # 빈 기간 = None(추정할 칸)
    ]
    assert rows.blanks == 1
    # WBS 코드는 앞부분으로 나무를 만든다. WBS 가 빈 행은 맨 위 「0」(파일 이름)
    assert [(n["code"], n["parent"]) for n in rows.wbs] == [("1", None), ("1.1", "1"), ("1.2", "1"), ("1.2.1", "1.2"),
                                                            ("0", None)]


def test_without_id_or_predecessor_columns(session, admin_user):
    plan = Plan(name_col="작업", duration_col="기간")
    rows = convert(table_of(session, admin_user, CSV), plan)
    assert [(r.id, r.preds) for r in rows.rows] == [("1", None), ("2", None), ("3", None)]  # 선행 열 없음 = 추정
    assert rows.blanks == 3 and [n["code"] for n in rows.wbs] == ["0"]


def test_convert_lists_every_unreadable_cell(session, admin_user):
    bad = "ID,작업,기간,선행,시작\nA,울타리,2주,,2027-03-02\nB,터파기,3,Z9,3월 2일\nA,중복,1,,\n"
    plan = Plan(id_col="ID", name_col="작업", duration_col="기간", pred_col="선행", start_col="시작")
    with pytest.raises(ImportProblem) as caught:
        convert(table_of(session, admin_user, bad), plan)
    message = caught.value.message
    for part in ["2행 기간 '2주'", "3행 선행: 없는 액티비티입니다: Z9", "3행 시작일 '3월 2일'", "4행 ID 가 겹칩니다: A"]:
        assert part in message


def test_cycles_in_the_file_are_refused(session, admin_user):
    looped = "ID,작업,기간,선행\nA,울타리,1,B\nB,터파기,2,A\nC,방수,1,\n"
    with pytest.raises(ImportProblem, match="고리를 이룹니다: A, B"):
        convert(table_of(session, admin_user, looped), PLAN)


def test_without_a_name_column_nothing_is_imported(session, admin_user):
    with pytest.raises(ImportProblem, match="작업 이름 열"):
        convert(table_of(session, admin_user, CSV), Plan(id_col="ID"))


def test_agent_column_names_must_be_in_the_header(session, admin_user):
    table = table_of(session, admin_user, CSV)
    got = plan_from({"id_col": "ID", "name_col": "작업명", "duration_col": "기간", "blanks": "ask", "extra": 1}, table)
    assert (got.id_col, got.name_col, got.duration_col, got.blanks) == ("ID", None, "기간", "ask")  # 없는 열은 null
    with pytest.raises(ImportProblem, match="표를 판단하지 못했습니다"):
        plan_from({"blanks": "maybe"}, table)


def test_full_width_digits_are_refused():
    """M4: 화면 문법과 같이 ASCII 숫자만 — 전각 숫자(「SS+１５」「５」)는 읽지 않는다."""
    with pytest.raises(ValueError, match="선행 형식이 맞지 않습니다"):
        predecessors("A1 SS+１５", {"A1"})
    with pytest.raises(ValueError):
        duration("５")
    with pytest.raises(ValueError):
        day("２０２７-03-02")
