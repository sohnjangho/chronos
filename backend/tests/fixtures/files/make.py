"""시험용 작은 가상 파일을 이 폴더에 만든다(Task 47). 다시 만들려면: cd backend && .venv/bin/python tests/fixtures/files/make.py

사람·회사·현장은 모두 가상이다(5층 사무동 신축 · A현장).
"""

import struct
import zipfile
import zlib
from pathlib import Path

from openpyxl import Workbook
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

HERE = Path(__file__).parent

CSV_ROWS = ["공종,작업,기간(일)", "골조,1층 기둥 타설,5", "골조,2층 슬래브 타설,4", "전기,배관 매립,3"]
PDF_PAGES = [
    "Concrete strength C24 is required for the 5F office building slab. Curing takes 7 days.",
    "Rebar inspection precedes every pour. Formwork removal after 14 days for beams.",
]


def png() -> bytes:
    """1×1 흰 점."""
    def part(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + part(b"IHDR", ihdr) + part(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + part(b"IEND", b"")


def _text_page(writer: PdfWriter, text: str) -> None:
    page = writer.add_blank_page(612, 792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 11 Tf 40 700 Td ({text}) Tj ET".encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)


def pdf(pages: list[str], password: str | None = None) -> bytes:
    writer = PdfWriter()
    for text in pages:
        _text_page(writer, text)
    if password:
        writer.encrypt(password, algorithm="RC4-128")
    path = HERE / "_tmp.pdf"
    writer.write(path)
    data = path.read_bytes()
    path.unlink()
    return data


def scanned_pdf() -> bytes:
    """글 없는 쪽 셋(스캔 흉내)."""
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(612, 792)
    path = HERE / "_tmp.pdf"
    writer.write(path)
    data = path.read_bytes()
    path.unlink()
    return data


def xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "공정표"
    for row in [("ID", "작업", "기간"), ("A10", "기초 터파기", 6), ("A20", "골조 1층", 8)]:
        ws.append(row)
    other = wb.create_sheet("자원")
    other.append(("자원", "수량"))
    other.append(("타워크레인", 1))
    path = HERE / "_tmp.xlsx"
    wb.save(path)
    data = path.read_bytes()
    path.unlink()
    return data


def _zip(members: dict[str, str]) -> bytes:
    path = HERE / "_tmp.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in members.items():
            z.writestr(name, text)
    data = path.read_bytes()
    path.unlink()
    return data


def docx() -> bytes:
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = (f'<w:document xmlns:w="{w}"><w:body>'
            "<w:p><w:r><w:t>회의록 — 5층 사무동 신축</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>골조 공사는 </w:t></w:r><w:r><w:t>다음 주 월요일 시작.</w:t></w:r></w:p>"
            "</w:body></w:document>")
    return _zip({"[Content_Types].xml": "<Types/>", "word/document.xml": body})


def hwpx() -> bytes:
    hp = "http://www.hancom.co.kr/hwpml/2011/paragraph"
    section = (f'<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" xmlns:hp="{hp}">'
               "<hp:p><hp:run><hp:t>시방서 — 철근 콘크리트 공사</hp:t></hp:run></hp:p>"
               "<hp:p><hp:run><hp:t>타설 후 7일 양생한다.</hp:t></hp:run></hp:p></hs:sec>")
    return _zip({"mimetype": "application/hwp+zip", "Contents/section0.xml": section})


def encrypted_xlsx() -> bytes:
    """암호 걸린 Office 파일 흉내: CFB 머리 + EncryptionInfo 항목 이름."""
    head = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 504
    return head + "EncryptionInfo".encode("utf-16-le") + b"\x00" * 512


def main() -> None:
    files = {
        "dot.png": png(),
        "schedule_utf8.csv": ("\n".join(CSV_ROWS) + "\n").encode("utf-8"),
        "schedule_cp949.csv": ("\n".join(CSV_ROWS) + "\n").encode("cp949"),
        "notes.txt": "현장 메모: A현장 골조 반장 김하늘.\n".encode("cp949"),
        "plan.xlsx": xlsx(),
        "locked.xlsx": encrypted_xlsx(),
        "spec.pdf": pdf(PDF_PAGES),
        "locked.pdf": pdf(PDF_PAGES, password="fictional-pass"),
        "scanned.pdf": scanned_pdf(),
        "minutes.docx": docx(),
        "spec.hwpx": hwpx(),
    }
    for name, data in files.items():
        (HERE / name).write_bytes(data)


if __name__ == "__main__":
    main()
