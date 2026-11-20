"""공정표 파일 가져오기의 코드 쪽(설계 5-4): 표 전체 읽기, 판단 읽기, 행 → 액티비티, 빈 칸, 요약 카드.

판단(공정표인가·열의 뜻·빈 칸을 물을지·파일 날짜를 제약으로 둘지)은 에이전트가 하고 부르기는 도구(schedule.import)가 한다.
여기는 계산 쪽: 행 수·빈 칸 수·기간/선행/날짜 읽기·WBS 나무·파일 값 덮기. LLM 이 낸 숫자·날짜는 쓰지 않는다.
- 표 읽기: 글 뽑기(app.files.extract — 칸·인코딩·압축 폭탄 검사를 같이 씀)는 앞 200행뿐이라 원본을 다시 다 읽는다.
- 기간은 근무일 정수(「5일」), 선행은 화면 shared/schedule/predecessors.ts 꼴(「A1, A4 SS+15」), 숫자는 ASCII 만.
- 빈 칸: 기간 칸이 비었거나 기간 열이 없으면 기간을, 선행 열이 없으면 선행을 추정한다. 선행 열이 있으면 빈 칸은 「선행 없음」(파일 값).
"""

import csv
import io
import logging
import re
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Literal

from openpyxl import load_workbook
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from app.agent.generation_build import MAX_ACTIVITIES, MAX_LAG, MAX_OD, DraftProblem
from app.core.model import Constraint, Schedule
from app.files import extract
from app.llm.client import LlmReply, Usage
from app.store import files
from app.store.schedules import NotFound

logger = logging.getLogger(__name__)

ROW_LIMIT = 2000
ROOT = "0"  # WBS 칸이 빈 행이 들어가는 맨 위 WBS
COLUMNS = ("id_col", "name_col", "wbs_col", "duration_col", "pred_col", "start_col", "finish_col")
LABELS = {"id_col": "ID", "name_col": "이름", "wbs_col": "WBS", "duration_col": "기간", "pred_col": "선행",
          "start_col": "시작일", "finish_col": "종료일"}
NEEDED = ("name_col", "duration_col", "pred_col")  # 없으면 카드의 「빠진 것」
NOT_TABLE = "표 파일(csv·tsv·xlsx)만 공정표로 가져올 수 있습니다."
TOO_MANY = f"행이 {ROW_LIMIT:,}개를 넘어 가져올 수 없습니다. 표를 나눠 올려 주세요."
UNREAD = "표를 판단하지 못했습니다. 다시 시도해 주세요."
BLANK_LIMIT = 150  # 빈 칸 행이 이보다 많으면 추정하지 않는다(한 번의 추정 답이 max_tokens 안에 들게)
TOO_MANY_ROWS = "액티비티가 {}개입니다. 한 번에 " + f"{MAX_ACTIVITIES}개까지 가져올 수 있습니다 — 표를 나눠 주세요."
TOO_MANY_BLANKS = "빈 칸이 있는 행이 {}개로 많습니다 — 기간·선행 열을 채우거나 시트·범위를 좁혀 주세요"
REPAIR_NOTE = "가져온 공정표의 고침이다: '고친 초안 전체'·'전체 초안' 대신 '?' 칸이 있던 행만 activities 에 낸다(id 그대로)."

_DURATION = re.compile(r"(\d+)(?:\.0+)?\s*(?:일|근무일|d|days?)?", re.IGNORECASE | re.ASCII)
_PART = re.compile(r"(\S+)(?:\s+(FS|SS|FF|SF)([+-]\d+)?)?", re.IGNORECASE | re.ASCII)
_LAG_ONLY = re.compile(r"(\S+?)([+-]\d+)", re.ASCII)
_DAY = re.compile(r"(\d{4})\s*(?:[-./]|년)\s*(\d{1,2})\s*(?:[-./]|월)\s*(\d{1,2})\s*일?(?:[ T].*)?", re.ASCII)


class ImportProblem(Exception):
    """가져올 수 없다. message 는 사용자에게 그대로 보일 한국어 글."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Table:
    file_id: int
    name: str  # 파일 이름
    sheet: str | None  # 읽은 시트(csv 는 None)
    sheets: list[str]  # 엑셀의 모든 시트(csv 는 [])
    header: list[str]  # 빈 머리 칸은 「열 n」, 겹치면 「이름 (n열)」
    rows: list[tuple[int, list[str]]]  # (파일 행 번호, 칸 글) — 빈 행은 뺐다

    @property
    def title(self) -> str:
        return f"{self.name} · {self.sheet}" if self.sheet else self.name

    def index(self, column: str | None) -> int | None:
        return self.header.index(column) if column in self.header else None


def _text(value: object) -> str:
    return extract._cell(int(value) if isinstance(value, float) and value.is_integer() else value)


def _collect(numbered) -> list[tuple[int, list[str]]]:
    out = []
    for n, raw in numbered:
        cells = extract._trim([_text(v) for v in raw])
        if any(cells):
            out.append((n, cells))
            if len(out) > ROW_LIMIT + 1:  # 머리 + ROW_LIMIT 행까지
                raise ImportProblem(TOO_MANY)
    return out


def _csv(path: Path) -> list[tuple[int, list[str]]]:
    text = extract._decode(path.read_bytes())
    first = text.split("\n", 1)[0]
    delimiter = "\t" if first.count("\t") > first.count(",") else ","
    return _collect(enumerate(csv.reader(io.StringIO(text), delimiter=delimiter), start=1))


def _xlsx(path: Path, sheet: str | None) -> tuple[str, list[str], list[tuple[int, list[str]]]]:
    extract._check_office_zip(path)
    extract._check_sheet_size(path)
    with path.open("rb") as f:  # 파일 객체로 연다: 경로를 주면 openpyxl 이 확장자를 본다
        wb = load_workbook(f, read_only=True, data_only=True)
        try:
            names = list(wb.sheetnames)
            if sheet is not None and sheet not in names:
                raise ImportProblem(f"없는 시트입니다: {sheet} (시트: {', '.join(names)})")
            ws = wb[sheet or names[0]]
            return ws.title, names, _collect(enumerate(ws.iter_rows(values_only=True), start=1))
        finally:
            wb.close()


def _header(cells: list[str], width: int) -> list[str]:
    out: list[str] = []
    for i, cell in enumerate(cells + [""] * (width - len(cells))):
        name = cell or f"열 {i + 1}"
        out.append(f"{name} ({i + 1}열)" if name in out else name)
    return out


def read_table(session: Session, file_id: int, sheet: str | None) -> Table:
    """표 파일을 처음부터 끝까지 읽는다. 못 읽으면 ImportProblem(까닭)."""
    try:
        row = files.get(session, file_id)
    except NotFound:
        raise ImportProblem("파일을 찾을 수 없습니다.") from None
    if row.deleted_at is not None:
        raise ImportProblem("지워진 파일입니다.")
    if row.kind not in ("table", "sheet") or row.status == "failed":
        raise ImportProblem(NOT_TABLE if row.kind not in ("table", "sheet") else f"읽지 못한 파일입니다: {row.reason}")
    path = files.raw_path(row.sha256)
    try:
        name, names, lines = _xlsx(path, sheet) if row.kind == "sheet" else (None, [], _csv(path))
    except extract.ExtractError as e:
        raise ImportProblem(e.reason) from None
    except ImportProblem:
        raise
    except Exception as exc:  # 받은 파일은 무엇이든 될 수 있다: 라이브러리 오류는 「손상」으로 본다
        logger.warning("표를 읽지 못했습니다: kind=%s (%s)", row.kind, type(exc).__name__)
        raise ImportProblem(extract.BROKEN) from exc
    if not lines:
        raise ImportProblem("표가 비어 있습니다.")
    width = max(len(cells) for _, cells in lines)
    return Table(file_id, row.name, name, names, _header(lines[0][1], width), lines[1:])


class Plan(BaseModel):
    """에이전트의 판단: 열 대응(머리의 열 이름, 없으면 None)·빈 칸(ask|estimate)·파일 날짜를 제약으로 둘지."""

    model_config = ConfigDict(extra="ignore")  # 모르는 칸(날짜 등)은 버린다

    id_col: str | None = None
    name_col: str | None = None
    wbs_col: str | None = None
    duration_col: str | None = None
    pred_col: str | None = None
    start_col: str | None = None
    finish_col: str | None = None
    blanks: Literal["ask", "estimate"] = "estimate"
    questions: list[dict] = []  # ask 일 때 질문(ask.questionnaire 의 Question 모양 — 그 도구가 검사한다)
    start_constraint: bool = False
    finish_constraint: bool = False
    reason: str = ""


def plan_from(parsed: object, table: Table) -> Plan:
    """LLM 답을 읽는다. 머리에 없는 열 이름은 None(지어낸 열을 쓰지 않는다). 모양이 틀리면 ImportProblem."""
    try:
        got = Plan.model_validate(parsed)
    except ValidationError:
        raise ImportProblem(UNREAD) from None
    return got.model_copy(update={c: None for c in COLUMNS if getattr(got, c) not in table.header})


def _cells(table: Table, p: Plan) -> list[tuple[int, dict[str, str]]]:
    """가져올 행: (행 번호, {열 칸: 글}). ID 와 이름이 둘 다 빈 행은 뺀다."""
    at = {c: table.index(getattr(p, c)) for c in COLUMNS}
    out = []
    for n, cells in table.rows:
        got = {c: (cells[i] if i is not None and i < len(cells) else "") for c, i in at.items()}
        if got["id_col"] or got["name_col"] or (at["id_col"] is None and at["name_col"] is None):
            out.append((n, got))
    return out


def card(table: Table, p: Plan) -> dict:
    """요약 카드(코드가 센다): 행 수·찾은 열·빠진 것·열 대응·한도(over_limit: 행 > 400, blank_rows·blank_limit). kind 는 도구가."""
    rows = _cells(table, p)
    found = list(dict.fromkeys(getattr(p, c) for c in COLUMNS if getattr(p, c)))
    missing = [LABELS[c] for c in NEEDED if getattr(p, c) is None]
    if p.duration_col and (blank := sum(1 for _, got in rows if not got["duration_col"])):
        missing.append(f"기간 빈 칸 {blank}개")
    blanks = sum(1 for _, got in rows if not got["duration_col"] or table.index(p.pred_col) is None)
    return {"file_id": table.file_id, "sheet": table.sheet, "rows": len(rows), "columns_found": found, "missing": missing,
            "columns": p.model_dump(include={*COLUMNS, "start_constraint", "finish_constraint"}), "over_limit": len(rows) > MAX_ACTIVITIES, "blank_rows": blanks, "blank_limit": BLANK_LIMIT}


def duration(text: str) -> int:
    """근무일 정수. 못 읽으면 ValueError."""
    m = _DURATION.fullmatch(text.strip())
    if m is None or int(m.group(1)) > MAX_OD:
        raise ValueError(text)
    return int(m.group(1))


def predecessors(text: str, ids: set[str]) -> list[dict]:
    """「A1010, A1040 SS+15」 → [{pred, type, lag}]. 종류가 없으면 FS, 간격이 없으면 0. 틀리면 ValueError(까닭)."""
    out = []
    for part in (p.strip() for p in text.split(",")):
        if not part:
            continue
        m = _PART.fullmatch(part)
        if m is None:
            raise ValueError(f"선행 형식이 맞지 않습니다: {part}")
        if m.group(1) not in ids:
            lag = _LAG_ONLY.fullmatch(part)
            raise ValueError(f"관계 종류가 빠졌습니다: {part} (예: {lag[1]} SS{lag[2]})" if lag else f"없는 액티비티입니다: {m[1]}")
        lag = int(m.group(3) or 0)
        if abs(lag) > MAX_LAG:
            raise ValueError(f"선행 간격이 너무 큽니다: {part}")
        out.append({"pred": m.group(1), "type": (m.group(2) or "FS").upper(), "lag": lag})
    return out


def day(text: str) -> date:
    m = _DAY.fullmatch(text.strip())
    if m is None:
        raise ValueError(text)
    return date(int(m[1]), int(m[2]), int(m[3]))


def pred_text(items: list[dict]) -> str:
    """선행 목록 → 표의 글(FS 0 은 ID 만, 간격 0 은 종류까지)."""
    return ", ".join(p["pred"] if (p["type"], p["lag"]) == ("FS", 0)
                     else f"{p['pred']} {p['type']}" + (f"{p['lag']:+d}" if p["lag"] else "") for p in items)


@dataclass(frozen=True)
class ImportedRow:
    line: int  # 파일 행 번호
    id: str
    name: str
    wbs: str
    od: int | None  # None = 빈 칸(추정)
    preds: tuple[dict, ...] | None  # None = 선행 열 없음(추정), () = 선행 없음(파일 값)
    start: date | None
    finish: date | None

    @property
    def blank(self) -> bool:
        return self.od is None or self.preds is None

    def merged(self, a: dict, ids: set[str]) -> dict:
        """LLM 이 낸 한 줄 a 에 파일 값을 덮는다. 추정한 선행은 이 표의 다른 id 만 둔다."""
        if self.preds is not None:
            preds = list(self.preds)
        else:
            got = a.get("predecessors") if isinstance(a.get("predecessors"), list) else []
            preds = [p for p in got if isinstance(p, dict) and p.get("pred") in ids - {self.id}]
        if self.od is None:
            od, kind = a.get("od"), a.get("kind")
        else:
            od, kind = self.od, "task" if self.od else ("finish_ms" if preds else "start_ms")
        tags = a.get("tags") if isinstance(a.get("tags"), list) else []
        return {"id": self.id, "name": self.name, "kind": kind, "wbs": self.wbs, "od": od, "tags": tags,
                "predecessors": preds}


@dataclass(frozen=True)
class ImportedRows:
    """가져온 행 — 생성 루프의 「고정값」(generation.generate(fixed=…)). 파일 차례 그대로."""

    title: str
    rows: tuple[ImportedRow, ...]
    wbs: tuple[dict, ...]  # [{code, name, parent}] 부모가 먼저
    snet: bool = False  # 파일 시작일을 SNET 으로(에이전트 판단)
    fnlt: bool = False  # 파일 종료일을 FNLT 로(시작일 SNET 이 없는 액티비티만 — 제약은 하나)

    @property
    def blanks(self) -> int:
        return sum(r.blank for r in self.rows)

    def merge(self, reply: LlmReply | None) -> LlmReply:
        """LLM 답에 파일 값을 덮는다(파일 행만·파일 차례, None 이면 파일 값만). 읽을 수 없는 답(JSON 아님·잘림)은 그대로
        두고(깨진 초안), 빈 칸 행이 답에 없으면 DraftProblem(같은 고침 루프로 돌려보낸다)."""
        reply = reply or LlmReply("", [], "file", Usage(0, 0, None), parsed={})
        if not isinstance(reply.parsed, dict) or reply.finish_reason == "length":
            return reply
        items = reply.parsed.get("activities") if isinstance(reply.parsed.get("activities"), list) else []
        got = {str(a["id"]): a for a in items if isinstance(a, dict) and isinstance(a.get("id"), str | int)}
        missing = [r.id for r in self.rows if r.blank and r.id not in got]
        if missing:
            more = f" 외 {len(missing) - 10}개" if len(missing) > 10 else ""
            raise DraftProblem(f"빈 칸('?')을 채울 액티비티가 답에 없습니다: {', '.join(missing[:10])}{more}", len(got))
        ids = {r.id for r in self.rows}
        return replace(reply, parsed={"wbs": None, "activities": [r.merged(got.get(r.id, {}), ids) for r in self.rows]})

    def constrain(self, schedule: Schedule) -> Schedule:
        """에이전트가 고른 대로 파일의 시작일(SNET)·종료일(FNLT)을 액티비티 제약으로. 날짜는 파일 값."""
        by_id = {r.id: r for r in self.rows}

        def one(a):
            r = by_id.get(a.id)
            if r is not None and self.snet and r.start:
                return replace(a, constraint=Constraint("SNET", r.start))
            if r is not None and self.fnlt and r.finish:
                return replace(a, constraint=Constraint("FNLT", r.finish))
            return a
        return replace(schedule, activities=tuple(one(a) for a in schedule.activities))

    def estimates(self, schedule: Schedule) -> list[dict]:
        """추정한 칸(가정, 출처 「추정」): 빈 칸이 있던 행마다 한 줄."""
        od = {a.id: a.od for a in schedule.activities}
        preds: dict[str, list[dict]] = {}
        for x in schedule.relations:
            preds.setdefault(x.succ, []).append({"pred": x.pred, "type": x.type, "lag": x.lag})
        out = []
        for r in self.rows:
            parts = [f"기간 {od.get(r.id)}일"] if r.od is None else []
            parts += [f"선행 {pred_text(preds.get(r.id, [])) or '없음'}"] if r.preds is None else []
            if parts:
                out.append({"label": f"{r.id} {r.name}", "value": " · ".join(parts), "source": "추정"})
        return out


def _wbs_nodes(codes: list[str], title: str) -> tuple[dict, ...]:
    """WBS 코드의 앞부분(「1.2.3」 → 1, 1.2, 1.2.3)으로 나무를 만든다. 이름은 코드, ROOT 는 파일 이름."""
    nodes: dict[str, dict] = {}
    for code in codes:
        if code == ROOT:
            nodes.setdefault(ROOT, {"code": ROOT, "name": title, "parent": None})
            continue
        parent = None
        parts = code.split(".")
        for i in range(1, len(parts) + 1):
            c = ".".join(parts[:i])
            nodes.setdefault(c, {"code": c, "name": c, "parent": parent})
            parent = c
    return tuple(nodes.values())


def _cycle(rows: list[ImportedRow]) -> list[str]:
    """선행 관계의 고리에 걸린 id(행 차례), 없으면 []."""
    waiting = {r.id: len(r.preds or ()) for r in rows}
    after: dict[str, list[str]] = {}
    for r in rows:
        for p in r.preds or ():
            after.setdefault(p["pred"], []).append(r.id)
    ready = [i for i, n in waiting.items() if n == 0]
    while ready:
        for s in after.get(ready.pop(), []):
            waiting[s] -= 1
            if waiting[s] == 0:
                ready.append(s)
    return [r.id for r in rows if waiting[r.id] > 0]


def _parse(text: str, label: str, line: int, problems: list[str], read):
    if not text:
        return None
    try:
        return read(text)
    except ValueError as e:
        problems.append(f"{line}행 {label}: {e}" if label == "선행" else f"{line}행 {label} '{text}'")
        return None


def convert(table: Table, p: Plan) -> ImportedRows:
    """행 → 액티비티(파일 값 그대로). 읽을 수 없는 칸·겹치는 ID·고리면 ImportProblem(행 번호와 함께)."""
    if table.index(p.name_col) is None:
        raise ImportProblem("작업 이름 열을 찾지 못해 가져올 수 없습니다.")
    rows = _cells(table, p)
    if not rows or len(rows) > MAX_ACTIVITIES:
        raise ImportProblem(TOO_MANY_ROWS.format(len(rows)) if rows else "가져올 행이 없습니다.")
    has = {c: table.index(getattr(p, c)) is not None for c in COLUMNS}
    ids = [(got["id_col"] or f"R{n}") if has["id_col"] else str(k) for k, (n, got) in enumerate(rows, start=1)]
    problems: list[str] = []
    seen: set[str] = set()
    for (n, _), i in zip(rows, ids, strict=True):
        if i in seen:
            problems.append(f"{n}행 ID 가 겹칩니다: {i}")
        seen.add(i)
    out = []
    for (n, got), i in zip(rows, ids, strict=True):
        od = _parse(got["duration_col"], "기간", n, problems, duration)
        preds = _parse(got["pred_col"], "선행", n, problems, lambda t: predecessors(t, seen))
        start, finish = (_parse(got[c], LABELS[c], n, problems, day) for c in ("start_col", "finish_col"))
        out.append(ImportedRow(n, i, got["name_col"] or i, got["wbs_col"] or ROOT, od,
                               tuple(preds or ()) if has["pred_col"] else None, start, finish))
    if problems:
        more = f" 외 {len(problems) - 8}개" if len(problems) > 8 else ""
        raise ImportProblem(f"읽을 수 없는 칸이 있습니다: {'; '.join(problems[:8])}{more}. 표를 고쳐 다시 올려 주세요.")
    if (blank := sum(r.blank for r in out)) > BLANK_LIMIT:  # LLM 을 부르기 전에(코드가 센다)
        raise ImportProblem(TOO_MANY_BLANKS.format(blank))
    if looped := _cycle(out):
        raise ImportProblem(f"선행 관계가 고리를 이룹니다: {', '.join(looped[:10])}. 표를 고쳐 다시 올려 주세요.")
    return ImportedRows(table.title, tuple(out), _wbs_nodes([r.wbs for r in out], table.title),
                        p.start_constraint, p.finish_constraint)
