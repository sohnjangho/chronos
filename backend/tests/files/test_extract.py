"""종류 고르기·글 뽑기·조각 나누기(app.files, Task 47)."""

import csv
import io
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.files.chunk import Chunk, chunks
from app.files.extract import ENCRYPTED, SCANNED, ExtractError, extract
from app.files.kinds import kind_of, refusal

FIXTURES = Path(__file__).parent.parent / "fixtures" / "files"


def test_kind_of():
    assert kind_of("사진.JPG", b"\xff\xd8\xff") == "image"
    assert [kind_of(n, b"") for n in ["a.csv", "a.tsv", "a.xlsx", "a.pdf", "a.docx", "a.hwpx", "a.md", "a.txt"]] == [
        "table", "table", "sheet", "pdf", "doc", "doc", "text", "text",
    ]
    assert kind_of("a.hwp", b"") is None and kind_of("a.zip", b"PK") is None and kind_of("noext", b"") is None
    assert kind_of("사진.png", b"MZ\x90\x00") is None and kind_of("a.pdf", b"#!/bin/sh") is None  # 실행 파일
    assert kind_of("세대.txt", b"MZ\xec\x84\xb8") == "text" and kind_of("a.md", b"#!x") == "text"  # 글은 막지 않는다


def test_refusal_messages():
    assert "PDF 로 저장해 주세요" in refusal("시방서.hwp")
    assert "xlsx 로 저장해 주세요" in refusal("공정표.xls")
    assert refusal("a.exe")  # 모르는 확장자도 안내 글이 있다


def test_pdf_pages_and_locators():
    got = extract(FIXTURES / "spec.pdf", "pdf")
    assert got.pages == 2 and not got.scanned
    assert [loc for loc, _ in got.text_parts] == ["1쪽", "2쪽"] and "C24" in got.text_parts[0][1]


def test_scanned_pdf():
    got = extract(FIXTURES / "scanned.pdf", "pdf")
    assert got.scanned and got.pages == 3
    assert SCANNED == "스캔 문서라 글을 읽을 수 없습니다(OCR 미지원)"


def test_encrypted_files_raise_polite_error():
    for name, kind in [("locked.pdf", "pdf"), ("locked.xlsx", "sheet")]:
        with pytest.raises(ExtractError) as e:
            extract(FIXTURES / name, kind)
        assert e.value.reason == ENCRYPTED == "암호가 걸린 파일이라 읽을 수 없습니다"


def test_broken_file_raises_polite_error(tmp_path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.7 nonsense")
    with pytest.raises(ExtractError) as e:
        extract(path, "pdf")
    assert e.value.reason == "파일이 손상되었거나 형식이 맞지 않아 읽을 수 없습니다"


def test_csv_first_200_rows_with_header_in_each_block(tmp_path):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter="\t")
    w.writerow(["ID", "작업"])
    for i in range(1, 301):
        w.writerow([f"A{i}", f"작업 {i}"])
    path = tmp_path / "big.tsv"
    path.write_text(buf.getvalue(), encoding="utf-8")
    got = extract(path, "table")
    text = "\n".join(t for _, t in got.text_parts)
    assert "A199 | 작업 199" in text and "A200 " not in text  # 머리 1행 + 199행 = 앞 200행
    assert got.text_parts[0][0] == "행 1–20" and got.text_parts[1][1].startswith("ID | 작업\n")


def test_cp949_csv_and_text():
    assert "골조" in extract(FIXTURES / "schedule_cp949.csv", "table").text_parts[0][1]
    assert "김하늘" in extract(FIXTURES / "notes.txt", "text").text_parts[0][1]


def test_xlsx_values_per_sheet(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "공정표"
    for i in range(250):
        ws.append([f"A{i}", i])
    wb.create_sheet("자원").append(["타워크레인", 1])
    path = tmp_path / "s.xlsx"
    wb.save(path)
    got = extract(path, "sheet")
    assert got.pages == 2
    sheets = {loc.split(" ")[0] for loc, _ in got.text_parts}
    assert sheets == {"공정표", "자원"}
    text = "\n".join(t for _, t in got.text_parts)
    assert "A199 | 199" in text and "A200" not in text and "타워크레인 | 1" in text


def test_docx_and_hwpx_text():
    assert "골조 공사는 다음 주 월요일 시작." in extract(FIXTURES / "minutes.docx", "doc").text_parts[0][1]
    assert "타설 후 7일 양생한다." in extract(FIXTURES / "spec.hwpx", "doc").text_parts[0][1]


def test_zip_member_too_large_is_refused(tmp_path):
    path = tmp_path / "bomb.docx"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "<a>" + " " * (60 * 1024 * 1024) + "</a>")
    with pytest.raises(ExtractError):
        extract(path, "doc")


def test_image_has_no_text():
    got = extract(FIXTURES / "dot.png", "image")
    assert got.text_parts == [] and not got.scanned


def test_chunks_split_long_part_with_overlap():
    body = "가" * 1000 + "\n" + "나" * 500
    got = chunks([("1쪽", body), ("2쪽", "짧은 쪽")], size=800, overlap=100)
    assert [c.seq for c in got] == list(range(len(got)))
    assert all(len(c.text) <= 800 for c in got)
    assert [c.locator for c in got][-1] == "2쪽" and got[-1].text == "짧은 쪽"
    first, second = got[0], got[1]
    assert first.text[-100:] == second.text[:100]  # 겹침 100자


def test_chunks_prefer_line_break():
    body = "\n".join(f"줄 {i:03d} " + "x" * 40 for i in range(40))
    got = chunks([("본문", body)], size=800, overlap=100)
    assert got[0].text.endswith("\n")


def test_chunks_skip_blank_parts():
    assert chunks([("1쪽", "   "), ("2쪽", "글")]) == [Chunk(0, "2쪽", "글")]


# ── Fix round 1 ─────────────────────────────────────────────────────


def _zip_with(path, members: dict[str, int]) -> None:
    """이름 → 풀었을 때 크기(공백). 1MB 씩 써서 메모리를 아낀다."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, size in members.items():
            with z.open(name, "w") as f:
                for _ in range(size // (1024 * 1024)):
                    f.write(b" " * (1024 * 1024))


@pytest.mark.parametrize("member, size", [
    ("xl/sharedStrings.xml", 31 * 1024 * 1024),  # 통째로 읽는 부분
    ("xl/worksheets/sheet1.xml", 201 * 1024 * 1024),  # 흘려 읽는 시트도 상한이 있다
])
def test_xlsx_zip_bomb_is_refused_before_openpyxl(tmp_path, monkeypatch, member, size):
    import app.files.extract as ex

    monkeypatch.setattr(ex, "load_workbook", lambda *a, **k: pytest.fail("openpyxl 을 불렀다"))
    path = tmp_path / "bomb.xlsx"
    _zip_with(path, {member: size})
    with pytest.raises(ExtractError) as e:
        extract(path, "sheet")
    assert e.value.reason == ex.TOO_BIG_INSIDE


def test_trailing_empty_cells_are_dropped(tmp_path):
    path = tmp_path / "a.csv"
    path.write_text("ID,작업,,,\nA1,골조,,,\n", encoding="utf-8")
    assert extract(path, "table").text_parts[0][1] == "ID | 작업\nA1 | 골조"
    wb = Workbook()
    wb.active.append(["A1", "골조"])
    wb.active["F1"].number_format = "0.00"  # 서식만 있는 빈 칸
    wb.active["F1"].value = None
    wb.active["G2"] = None
    book = tmp_path / "a.xlsx"
    wb.save(book)
    assert extract(book, "sheet").text_parts[0][1] == "A1 | 골조"
