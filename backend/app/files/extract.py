"""받은 파일에서 글을 뽑는다(설계 5-1 표). 원본 경로에는 확장자가 없으므로 형식은 종류(kind)와 내용으로 본다.

- table(csv·tsv): 앞 200행. 구분자는 첫 줄로 고른다(탭이 쉼표보다 많으면 tsv). 20행씩 묶고, 둘째 묶음부터 머리 행을 앞에 붙인다.
- sheet(xlsx): 시트마다 앞 200행, 값만(수식은 저장된 결과). 위치 「<시트> 행 a–b」.
- pdf: 앞 300쪽, 쪽마다 「n쪽」. 읽은 쪽의 글(공백 뺀 글자)이 쪽당 평균 20자 미만이면 scanned.
- doc(docx·hwpx): zip 안 XML 의 문단 글. 위치 「본문」.
- text(txt·md): UTF-8, 안 되면 CP949. 위치 「본문」.
- image: 글 없음(설명은 분류 단계, Task 49).
읽지 못하면 ExtractError(reason) — reason 은 화면에 그대로 보일 한국어 글.
"""

import csv
import io
import logging
import re
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

from openpyxl import load_workbook
from pypdf import PasswordType, PdfReader
from pypdf.errors import PyPdfError

logger = logging.getLogger(__name__)

ENCRYPTED = "암호가 걸린 파일이라 읽을 수 없습니다"
BROKEN = "파일이 손상되었거나 형식이 맞지 않아 읽을 수 없습니다"
SCANNED = "스캔 문서라 글을 읽을 수 없습니다(OCR 미지원)"
UNKNOWN_ENCODING = "글자 인코딩을 알 수 없어 읽을 수 없습니다(UTF-8·CP949 만 읽습니다)"
OLD_OFFICE = "옛 오피스 형식(xls·doc)으로 보여 읽을 수 없습니다. xlsx·docx 로 저장해 주세요"
TOO_BIG_INSIDE = "파일 안의 글이 너무 커서 읽을 수 없습니다"

MAX_ROWS = 200
MAX_PAGES = 300
ROW_BLOCK = 20
SCANNED_CHARS_PER_PAGE = 20
# 압축 폭탄 막기: zip 안 항목을 풀었을 때 크기(file_size)의 합. 열기 전에 본다.
MAX_XML_BYTES = 30 * 1024 * 1024  # 통째로 읽는 XML(docx·hwpx 본문, xlsx 의 시트 밖 — sharedStrings 등)
MAX_SHEET_XML_BYTES = 200 * 1024 * 1024  # xlsx 전체(시트 XML 은 흘려 읽고 앞 200행에서 멈춘다)
_SHEET_MEMBER = re.compile(r"xl/worksheets/[^/]+\.xml")
_CFB = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # 옛 오피스·암호 걸린 오피스 파일의 머리
_ENCRYPTION_INFO = "EncryptionInfo".encode("utf-16-le")
_SECTION = re.compile(r"Contents/section(\d+)\.xml")


class ExtractError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Extracted:
    text_parts: list[tuple[str, str]]  # [(위치, 글)]
    pages: int  # PDF 전체 쪽 수 · 시트 수 · 그 밖은 1
    scanned: bool


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ExtractError(UNKNOWN_ENCODING)


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime) and value.time() == datetime.min.time():
        return value.date().isoformat()
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def _trim(cells: list[str]) -> list[str]:
    """끝의 빈 칸을 뗀다(서식만 있는 빈 열이 글을 부풀리지 않게)."""
    end = len(cells)
    while end and not cells[end - 1]:
        end -= 1
    return cells[:end]


def _blocks(rows: Iterable[tuple[int, list[str]]], prefix: str = "") -> list[tuple[str, str]]:
    """[(행 번호, 칸)] → 20행 묶음 [(「<prefix>행 a–b」, 글)]. 빈 행은 뺀다. 둘째 묶음부터 첫 행(머리)을 앞에 붙인다."""
    lines = [(n, " | ".join(_trim(cells))) for n, cells in rows if any(cells)]
    parts = []
    for i in range(0, len(lines), ROW_BLOCK):
        block = lines[i:i + ROW_BLOCK]
        body = [line for _, line in block]
        if i > 0:
            body.insert(0, lines[0][1])
        parts.append((f"{prefix}행 {block[0][0]}–{block[-1][0]}", "\n".join(body)))
    return parts


def _table(path: Path) -> Extracted:
    text = _decode(path.read_bytes())
    first = text.split("\n", 1)[0]
    delimiter = "\t" if first.count("\t") > first.count(",") else ","
    rows = []
    for n, row in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter), start=1):
        if n > MAX_ROWS:
            break
        rows.append((n, [_cell(c) for c in row]))
    return Extracted(_blocks(rows), 1, False)


def _check_office_zip(path: Path) -> None:
    """암호 걸린 오피스 파일(CFB 안 EncryptionInfo)과 옛 형식을 알아본다."""
    with path.open("rb") as f:
        if f.read(len(_CFB)) != _CFB:
            return
    raise ExtractError(ENCRYPTED if _ENCRYPTION_INFO in path.read_bytes() else OLD_OFFICE)


def _check_sheet_size(path: Path) -> None:
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
    whole = sum(i.file_size for i in infos if not _SHEET_MEMBER.fullmatch(i.filename))
    if whole > MAX_XML_BYTES or sum(i.file_size for i in infos) > MAX_SHEET_XML_BYTES:
        raise ExtractError(TOO_BIG_INSIDE)


def _sheet(path: Path) -> Extracted:
    _check_office_zip(path)
    _check_sheet_size(path)
    with path.open("rb") as f:  # 파일 객체로 연다: 경로를 주면 openpyxl 이 확장자를 본다
        wb = load_workbook(f, read_only=True, data_only=True)
        try:
            parts = []
            for ws in wb.worksheets:
                rows = ws.iter_rows(min_row=1, max_row=MAX_ROWS, values_only=True)
                parts += _blocks(((n, [_cell(v) for v in row]) for n, row in enumerate(rows, start=1)), f"{ws.title} ")
            return Extracted(parts, len(wb.worksheets), False)
        finally:
            wb.close()


def _pdf(path: Path) -> Extracted:
    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            opened = reader.decrypt("") != PasswordType.NOT_DECRYPTED
        except (PyPdfError, NotImplementedError, ValueError):  # 지원하지 않는 암호 방식 등
            opened = False
        if not opened:
            raise ExtractError(ENCRYPTED)
    total = len(reader.pages)
    read = min(total, MAX_PAGES)
    parts, chars = [], 0
    for i in range(read):
        text = reader.pages[i].extract_text() or ""
        chars += len("".join(text.split()))
        if text.strip():
            parts.append((f"{i + 1}쪽", text))
    scanned = read > 0 and chars / read < SCANNED_CHARS_PER_PAGE
    return Extracted(parts, total, scanned)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _paragraphs(root: ElementTree.Element) -> list[str]:
    """문단(p) 마다 그 안의 글(t) 한 줄. 표 안 문단처럼 문단 속 문단은 따로 한 줄."""
    out: list[str] = []

    def walk(el: ElementTree.Element, buf: list[str]) -> None:
        name = _local(el.tag)
        if name == "p":
            mine: list[str] = []
            for child in el:
                walk(child, mine)
            if line := "".join(mine).strip():
                out.append(line)
            return
        if name == "t":
            buf.append("".join(el.itertext()))
            return
        for child in el:
            walk(child, buf)

    walk(root, [])
    return out


def _doc_members(z: zipfile.ZipFile) -> list[str]:
    names = z.namelist()
    if "word/document.xml" in names:
        return ["word/document.xml"]
    sections = [(int(m.group(1)), n) for n in names if (m := _SECTION.fullmatch(n))]
    if not sections:
        raise ExtractError(BROKEN)
    return [n for _, n in sorted(sections)]


def _doc(path: Path) -> Extracted:
    _check_office_zip(path)
    with zipfile.ZipFile(path) as z:
        members = _doc_members(z)
        if sum(z.getinfo(n).file_size for n in members) > MAX_XML_BYTES:
            raise ExtractError(TOO_BIG_INSIDE)
        lines = [line for n in members for line in _paragraphs(ElementTree.fromstring(z.read(n)))]
    return Extracted([("본문", "\n".join(lines))], 1, False)


def _text(path: Path) -> Extracted:
    return Extracted([("본문", _decode(path.read_bytes()))], 1, False)


def _image(_: Path) -> Extracted:
    return Extracted([], 1, False)


_READERS: dict[str, Callable[[Path], Extracted]] = {
    "table": _table, "sheet": _sheet, "pdf": _pdf, "doc": _doc, "text": _text, "image": _image,
}


def extract(path: Path, kind: str) -> Extracted:
    """kind 에 맞게 글을 뽑는다. 읽지 못하면 ExtractError(한국어 까닭). 모르는 kind 면 KeyError."""
    reader = _READERS[kind]
    try:
        return reader(path)
    except ExtractError:
        raise
    except Exception as exc:  # 받은 파일은 무엇이든 될 수 있다: 라이브러리 오류는 모두 「손상」으로 본다
        logger.warning("파일 글을 뽑지 못했습니다: kind=%s (%s)", kind, type(exc).__name__)
        raise ExtractError(BROKEN) from exc
