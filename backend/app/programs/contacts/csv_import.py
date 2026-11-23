"""CSV 가져오기(Task 76): 미리 보기(dry_run)와 넣기. 다른 프로젝트에서 복사(copy.py)도 「이미 있음」 판정(Book)을 같이 쓴다.

- 열은 머리줄 이름으로 찾는다(차례 무관): 협력사(필수)·이름(필수)·공종·담당·전화번호·성별(남|여|빈칸)·언어·메모. 모르는 열은
  버린다. UTF-8(BOM 있든 없든)·CP949 를 읽고, 둘 다 아니거나 NUL 이 든 파일은 글이 아니라고 거절한다. 1MB·500행까지
  (크기는 라우터가 몸을 읽기 전에 Content-Length 로 먼저 본다 — check_length). 모두 빈 행은 건너뛴다.
- 행 검사는 주소록 입력과 같은 함수다(service.check_texts·check_phone·check_channels — 번호 규칙은 phone 모듈 한 곳).
  글은 NFC 로 바꾸고 앞뒤 빈칸을 지운 뒤 길이(주소록 입력과 같은 상한)와 글자를 본다. 근무시간·음성 열은 없으므로 넣는
  사람은 입력 칸을 비운 사람과 같다(근무시간 = 프로젝트 기본, 음성 auto). 수식처럼 생긴 칸(=·+·-·@)은 쓴 그대로의 글이다.
- 판정 result: new | exists(같은 번호 — 정리한 꼴로 — 또는 같은 협력사·이름, 이 프로젝트나 이 파일의 앞 행) | no_phone(넣되
  보내기 불가) | bad_phone | bad_row. 까닭은 검사 함수의 한국어 글 그대로이고 걸린 값은 어디에도 싣지 않는다(그 칸은 null).
- 미리 보기는 아무것도 쓰지 않는다. 넣기는 파일을 처음부터 다시 검사하고 쓰기 트랜잭션(BEGIN IMMEDIATE) 하나에서 판정·
  넣기를 한다 — new·no_phone 이 모두 들어가거나 하나도 들어가지 않는다. 없는 협력사는 만든다(같은 이름의 보이는 협력사가
  있으면 그것에 넣고, 그 공종·메모는 바꾸지 않는다).
- 응답의 번호는 가린 꼴(맞으면 phone.mask, 틀리면 phone.mask_bad)과 종류뿐, 글 칸은 hide_phones 를 거친다. 로그는 셈 한 줄.
"""

import codecs
import csv
import io
import logging
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.orm import Session
from starlette.datastructures import Headers

from app.errors import ApiError
from app.outreach import phone
from app.outreach.redact import hide_phones
from app.programs.contacts import service
from app.programs.contacts.schemas import ImportOut, ImportRowOut, ImportSummary
from app.store import outreach
from app.store.tables import User
from app.store.tables_outreach import Contact, ContactCompany

logger = logging.getLogger(__name__)

MAX_ROWS = 500
MAX_BYTES = 1024 * 1024
MAX_BODY_BYTES = MAX_BYTES + 64 * 1024  # multipart 머리·경계·skip 칸 여유
MAX_FIELDS = MAX_ROWS + 10  # skip 을 한 칸에 하나씩 보내도 되게
COLUMNS = {"협력사": "company", "이름": "name", "공종": "trade", "담당": "role_title", "전화번호": "phone",
           "성별": "gender", "언어": "language", "메모": "note"}
REQUIRED = ("협력사", "이름")
LABELS = {key: label for label, key in COLUMNS.items()}
# 글 칸 → (service.check_texts 가 보는 칸 이름, 길이 상한 — schemas.Name·Short·Note 와 같음)
TEXTS = {"company": ("name", 100), "name": ("name", 100), "trade": ("trade", 100), "role_title": ("role_title", 100),
         "note": ("note", 2000)}
GENDERS = {"": "unknown", "남": "male", "여": "female"}
LANGUAGES = {"": "ko", "ko": "ko", "한국어": "ko", "en": "en", "영어": "en", "zh": "zh", "중국어": "zh",
             "vi": "vi", "베트남어": "vi"}
GOES_IN = ("new", "no_phone")

NO_LENGTH = "올리는 크기를 알 수 없습니다. 다시 올려 주세요."
TOO_BIG = "CSV 파일은 1MB 까지 올릴 수 있습니다."
NO_FILE = "가져올 CSV 파일을 골라 주세요."
NOT_TEXT = "CSV 파일을 읽을 수 없습니다. UTF-8 또는 CP949(한글 Windows) 글자로 저장한 CSV 파일만 받습니다."
UNREADABLE = "CSV 파일의 칸을 나눌 수 없습니다. 따옴표가 닫히지 않은 칸이 있는지 확인해 주세요."
NO_HEADER = "CSV 파일 첫 줄에 열 이름(협력사·이름 …)이 있어야 합니다."
MISSING_COLUMNS = "CSV 파일 첫 줄에 「협력사」·「이름」 열이 있어야 합니다."
DUPLICATE_COLUMN = "CSV 파일 첫 줄에 같은 열 이름이 두 번 있습니다."
TOO_MANY_ROWS = "CSV 는 한 번에 500행까지 넣을 수 있습니다."
BAD_SKIP = "건너뛸 행 번호는 숫자로 보내 주세요."
MISSING_VALUE = "협력사와 이름은 비울 수 없습니다."
TOO_LONG = "글이 너무 깁니다(협력사·이름·공종·담당 100자, 메모 2000자까지)."
BAD_GENDER = "성별은 「남」·「여」 또는 빈칸으로 넣어 주세요."
BAD_LANGUAGE = "언어는 한국어·영어·중국어·베트남어(ko·en·zh·vi) 또는 빈칸으로 넣어 주세요."
EXISTS = {
    ("here", "number"): "같은 번호가 이 프로젝트에 이미 있습니다.",
    ("here", "person"): "같은 협력사에 같은 이름이 이 프로젝트에 이미 있습니다.",
    ("file", "number"): "이 파일의 앞 행과 번호가 같습니다.",
    ("file", "person"): "이 파일의 앞 행과 협력사·이름이 같습니다.",
}


# ── 이미 있음(가져오기·복사 공통) ─────────────────────────────────────────────────────

@dataclass
class Book:
    """한 일정의 「이미 있음」 판정 자료. numbers = 모든 사람(숨긴 사람도)의 정리한 번호, people = 보이는 협력사의 보이는
    사람 (협력사 이름, 이름), companies = 보이는 협력사 이름 → id(같은 이름이면 먼저 만든 것)."""

    numbers: set[str] = field(default_factory=set)
    people: set[tuple[str, str]] = field(default_factory=set)
    companies: dict[str, int] = field(default_factory=dict)

    def match(self, company: str, name: str, number: str | None) -> str | None:
        """'number'(같은 번호) · 'person'(같은 협력사·이름) · None."""
        if number is not None and number in self.numbers:
            return "number"
        return "person" if (company, name) in self.people else None

    def add(self, company: str, name: str, number: str | None) -> None:
        if number is not None:
            self.numbers.add(number)
        self.people.add((company, name))


def existing(session: Session, schedule_id: int) -> Book:
    book = Book()
    names: dict[int, str] = {}
    for row in session.scalars(select(ContactCompany).where(
            ContactCompany.schedule_id == schedule_id, ContactCompany.hidden.is_(False)).order_by(ContactCompany.id)):
        book.companies.setdefault(row.name, row.id)
        names[row.id] = row.name
    people = session.execute(select(Contact.phone, Contact.name, Contact.company_id, Contact.hidden)
                             .where(Contact.schedule_id == schedule_id))
    for number, name, company_id, hidden in people:
        if number and (local := phone.normalize(number)) is not None:
            book.numbers.add(local)
        if not hidden and company_id in names:
            book.people.add((names[company_id], name))
    return book


def company_id(session: Session, schedule_id: int, book: Book, name: str, trade: str, note: str = "") -> int:
    """같은 이름의 보이는 협력사 id, 없으면 만들고(flush) 그 id."""
    if name not in book.companies:
        row = ContactCompany(schedule_id=schedule_id, name=name, trade=trade, note=note)
        session.add(row)
        session.flush()
        book.companies[name] = row.id
    return book.companies[name]


def begin_write(session: Session) -> None:
    """지금 트랜잭션을 끝내고 쓰기 트랜잭션(BEGIN IMMEDIATE)을 연다 — 판정(읽기)과 넣기가 한 덩어리(두 요청이 같은 사람을
    함께 넣지 못한다)."""
    session.rollback()
    session.execute(text("BEGIN IMMEDIATE"))


# ── 파일 읽기 ───────────────────────────────────────────────────────────────────

def check_length(headers: Headers) -> None:
    """몸을 읽기 전에: Content-Length 가 없거나(chunked) 한도를 넘으면 거절."""
    length = headers.get("content-length", "")
    if "transfer-encoding" in headers or not length.isdigit():
        raise ApiError(411, "length_required", NO_LENGTH)
    if int(length) > MAX_BODY_BYTES:
        raise ApiError(413, "csv_too_large", TOO_BIG)


def skip_rows(values: list) -> set[int]:
    """multipart 의 skip 칸들(한 칸에 하나, 또는 「3,5」처럼 쉼표·빈칸으로 여럿) → 행 번호."""
    rows: set[int] = set()
    for value in values:
        if not isinstance(value, str):
            raise ApiError(422, "invalid_request", BAD_SKIP)
        for part in value.replace(",", " ").split():
            if not (part.isascii() and part.isdigit() and len(part) <= 6):
                raise ApiError(422, "invalid_request", BAD_SKIP)
            rows.add(int(part))
    return rows


def _decode(data: bytes) -> str:
    if b"\x00" in data:
        raise ApiError(422, "csv_not_text", NOT_TEXT)
    if data.startswith(codecs.BOM_UTF8):
        encodings, data = ("utf-8",), data[len(codecs.BOM_UTF8):]
    else:
        encodings = ("utf-8", "cp949")
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ApiError(422, "csv_not_text", NOT_TEXT)


def _clean(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip()


@dataclass
class Row:
    n: int  # 파일의 행 번호(머리줄 = 1)
    cells: dict[str, str]  # 칸(company·name·…) → NFC·앞뒤 빈칸 지운 글. 없는 열은 ""


def parse(data: bytes) -> list[Row]:
    """파일 → 자료 행. 파일 자체의 문제는 422/413(한국어, 셀 값 없이)."""
    if len(data) > MAX_BYTES:
        raise ApiError(413, "csv_too_large", TOO_BIG)
    content = _decode(data).replace("\r\n", "\n").replace("\r", "\n")  # 칸 안의 줄 바꿈도 \n 하나로
    reader = csv.reader(io.StringIO(content), strict=True)
    rows: list[Row] = []
    try:
        header = next(reader, None)
        if not header or not any(cell.strip() for cell in header):
            raise ApiError(422, "csv_no_header", NO_HEADER)
        positions: dict[str, int] = {}
        for index, label in enumerate(_clean(cell) for cell in header):
            if label in COLUMNS:
                if COLUMNS[label] in positions:
                    raise ApiError(422, "csv_duplicate_column", DUPLICATE_COLUMN, detail={"column": label})
                positions[COLUMNS[label]] = index
        missing = [label for label in REQUIRED if COLUMNS[label] not in positions]
        if missing:
            raise ApiError(422, "csv_missing_column", MISSING_COLUMNS, detail={"missing": missing})
        for n, record in enumerate(reader, start=2):
            if not any(cell.strip() for cell in record):
                continue
            if len(rows) == MAX_ROWS:
                raise ApiError(422, "csv_too_many_rows", TOO_MANY_ROWS)
            cells = {key: _clean(record[i]) if i < len(record) else "" for key, i in positions.items()}
            rows.append(Row(n, {key: cells.get(key, "") for key in COLUMNS.values()}))
    except csv.Error:
        raise ApiError(422, "csv_unreadable", UNREADABLE) from None
    return rows


# ── 행 판정 ─────────────────────────────────────────────────────────────────────

def _row_problem(cells: dict[str, str]) -> tuple[str, str, str] | None:
    """번호 밖의 검사 — 처음 걸린 것의 (코드, 까닭, 칸). 글자 검사는 주소록 입력의 service.check_texts 그대로."""
    for key in ("company", "name"):
        if not cells[key]:
            return "missing_value", MISSING_VALUE, key
    for key, (as_field, limit) in TEXTS.items():
        if len(cells[key]) > limit:
            return "too_long", TOO_LONG, key
        try:
            service.check_texts({as_field: cells[key]})
        except ApiError as exc:
            return exc.code, exc.message, key
    if cells["gender"] not in GENDERS:
        return "invalid_gender", BAD_GENDER, "gender"
    if cells["language"] not in LANGUAGES:
        return "invalid_language", BAD_LANGUAGE, "language"
    return None


@dataclass
class Judged:
    row: Row
    out: ImportRowOut
    number: str | None = None
    channels: dict[str, bool] = field(default_factory=dict)

    @property
    def goes_in(self) -> bool:
        return not self.out.skipped and self.out.result in GOES_IN


def _judge_one(row: Row, book: Book, seen: Book, skipped: bool) -> Judged:
    cells = row.cells
    raw = cells["phone"]
    problem = _row_problem(cells)
    shown = {key: (None if problem and problem[2] == key else hide_phones(cells[key]))
             for key in ("company", "name", "role_title")}
    out = ImportRowOut(n=row.n, **shown, phone_shown=phone.mask(raw or None), phone_kind=phone.kind(raw or None),
                       do_not_contact=False, result="bad_row", reason=None, code=None, column=None, skipped=skipped)
    judged = Judged(row, out)
    if problem is not None:
        out.code, out.reason, out.column = problem[0], problem[1], LABELS[problem[2]]
        return judged
    try:
        judged.number = service.check_phone(raw)
    except ApiError as exc:
        out.result, out.code, out.reason = "bad_phone", exc.code, exc.message
        return judged
    judged.channels = service.check_channels(judged.number, {}, renumbered=True)
    for where, found in (("here", book), ("file", seen)):
        if (same := found.match(cells["company"], cells["name"], judged.number)) is not None:
            out.result, out.reason = "exists", EXISTS[(where, same)]
            return judged
    out.result = "new" if judged.number else "no_phone"
    if not skipped:
        seen.add(cells["company"], cells["name"], judged.number)
    return judged


def _judge(session: Session, rows: list[Row], book: Book, skip: set[int]) -> list[Judged]:
    seen = Book()
    judged = [_judge_one(row, book, seen, row.n in skip) for row in rows]
    refused = outreach.do_not_contact_numbers(session, [j.number for j in judged if j.number])
    for j in judged:
        j.out.do_not_contact = j.number in refused
    return judged


def _add_person(session: Session, schedule_id: int, company: int, judged: Judged) -> None:
    cells = judged.row.cells
    session.add(Contact(
        schedule_id=schedule_id, company_id=company, name=cells["name"], role_title=cells["role_title"],
        phone=judged.number, **judged.channels, hours_json=None, gender=GENDERS[cells["gender"]],
        language=LANGUAGES[cells["language"]], voice_mode="auto", voice_id=None, note=cells["note"],
    ))


def _summary(judged: list[Judged]) -> ImportSummary:
    results = [j.out.result for j in judged if not j.out.skipped]
    return ImportSummary(new=results.count("new"), exists=results.count("exists"), no_phone=results.count("no_phone"),
                         bad=results.count("bad_phone") + results.count("bad_row"),
                         skipped=sum(j.out.skipped for j in judged))


def run(session: Session, schedule_id: int, data: bytes, skip_values: list, *, dry_run: bool, user: User) -> ImportOut:
    """미리 보기(dry_run) 또는 넣기. 넣기는 미리 보기 결과를 믿지 않고 파일을 다시 판정한다(모듈 머리 글)."""
    skip = skip_rows(skip_values)
    service._schedule(session, schedule_id)  # 같은 꾸러미의 찾기 — 없는 일정은 주소록 API 와 같은 404
    rows = parse(data)
    if not dry_run:
        begin_write(session)
    book = existing(session, schedule_id)
    judged = _judge(session, rows, book, skip)
    if not dry_run:
        for j in judged:
            if j.goes_in:
                cells = j.row.cells
                _add_person(session, schedule_id, company_id(session, schedule_id, book, cells["company"],
                                                             cells["trade"]), j)
        session.commit()
    summary = _summary(judged)
    logger.info("연락처 가져오기(%s): 일정 %s · 사용자 %s · %d행 · 새 %d · 번호 없음 %d · 이미 있음 %d · 오류 %d · 건너뜀 %d",
                "미리 보기" if dry_run else "넣기", schedule_id, user.id, len(judged), summary.new, summary.no_phone,
                summary.exists, summary.bad, summary.skipped)
    return ImportOut(rows=[j.out for j in judged], summary=summary)
