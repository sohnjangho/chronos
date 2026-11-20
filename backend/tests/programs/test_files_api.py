"""파일 API(Task 47): 받기(한도·같은 내용 한 벌)·글 뽑기 결과·보기·원본·지우기."""

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.files import extract as extract_module
from app.store.tables import ChatSessionFile, FileChunk, FileRow

FIXTURES = Path(__file__).parent.parent / "fixtures" / "files"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def upload(client, headers, *files: tuple[str, bytes], chat_id: int | None = None, status: int = 200):
    data = {"chat_id": str(chat_id)} if chat_id is not None else {}
    r = client.post("/api/files", files=[("files", f) for f in files], data=data, headers=headers)
    assert r.status_code == status, r.text
    return r.json()


def chunks_text(session, file_id: int) -> str:
    session.expire_all()
    return "\n".join(session.scalars(select(FileChunk.text).where(FileChunk.file_id == file_id).order_by(FileChunk.seq)))


@pytest.fixture
def chat_a(client, admin) -> int:
    return client.post("/api/chat/sessions", json={}, headers=admin).json()["id"]


@pytest.fixture
def chat_b(client, admin) -> int:
    return client.post("/api/chat/sessions", json={}, headers=admin).json()["id"]


# ── Review Focus ─────────────────────────────────────────────────────


def test_same_content_twice_is_one_file_two_links(client, admin, session, chat_a, chat_b, monkeypatch):
    calls = []
    real = extract_module.extract
    monkeypatch.setattr(extract_module, "extract", lambda path, kind: calls.append(kind) or real(path, kind))
    a = upload(client, admin, ("spec.pdf", fixture("spec.pdf")), chat_id=chat_a)["items"][0]
    b = upload(client, admin, ("사본.pdf", fixture("spec.pdf")), chat_id=chat_b)["items"][0]
    assert a["file_id"] == b["file_id"] and a["status"] == b["status"] == "extracted"
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(FileRow)) == 1
    links = session.execute(select(ChatSessionFile.session_id, ChatSessionFile.file_id)).all()
    assert sorted(links) == [(chat_a, a["file_id"]), (chat_b, a["file_id"])]
    assert calls == ["pdf"]  # 글 뽑기는 한 번


def test_cp949_csv_and_korean_name(client, admin, session):
    r = upload(client, admin, ("공정표_A현장.csv", fixture("schedule_cp949.csv")))["items"][0]
    assert r["name"] == "공정표_A현장.csv" and r["kind"] == "table" and r["status"] == "extracted"
    assert "골조" in chunks_text(session, r["file_id"])
    got = client.get(f"/api/files/{r['file_id']}", headers=admin).json()
    assert got["name"] == "공정표_A현장.csv"


def test_encrypted_pdf_fails_politely(client, admin, session):
    r = upload(client, admin, ("locked.pdf", fixture("locked.pdf")))["items"][0]
    assert r["status"] == "failed" and r["reason"] == "암호가 걸린 파일이라 읽을 수 없습니다"
    assert chunks_text(session, r["file_id"]) == ""
    assert client.get(f"/api/files/{r['file_id']}/raw", headers=admin).content == fixture("locked.pdf")  # 원본은 보관


def test_encrypted_xlsx_fails_politely(client, admin):
    r = upload(client, admin, ("잠긴_공정표.xlsx", fixture("locked.xlsx")))["items"][0]
    assert r["status"] == "failed" and r["reason"] == "암호가 걸린 파일이라 읽을 수 없습니다"


# ── 지시서 시험 ─────────────────────────────────────────────────────


def test_scanned_pdf_is_kept_but_marked(client, admin):
    r = upload(client, admin, ("scan.pdf", fixture("scanned.pdf")))["items"][0]
    assert r["status"] == "extracted" and r["reason"] == "스캔 문서라 글을 읽을 수 없습니다(OCR 미지원)"
    assert client.get(f"/api/files/{r['file_id']}", headers=admin).json()["pages"] == 3


def test_limits(client, admin):
    big = upload(client, admin, ("big.txt", b"a" * (50 * 1024 * 1024 + 1)), status=413)
    assert big["message"] == "파일이 너무 큽니다(50MB까지)"
    many = upload(client, admin, *[(f"n{i}.txt", f"메모 {i}".encode()) for i in range(11)], status=422)
    assert many["message"] == "한 번에 10개까지 올릴 수 있습니다"
    hwp = upload(client, admin, ("시방서.hwp", b"HWP Document File"), status=422)
    assert "PDF 로 저장해 주세요" in hwp["message"]
    assert client.get("/api/files/1", headers=admin).status_code == 404  # 아무것도 저장하지 않았다


def test_mixed_batch_with_one_refused_saves_nothing(client, admin, session):
    upload(client, admin, ("a.txt", b"memo"), ("plan.xls", b"\xd0\xcf\x11\xe0"), status=422)
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(FileRow)) == 0


def test_each_kind_extracts(client, admin, session):
    items = upload(client, admin, *[(n, fixture(n)) for n in [
        "dot.png", "schedule_utf8.csv", "notes.txt", "plan.xlsx", "spec.pdf", "minutes.docx", "spec.hwpx",
    ]])["items"]
    assert [(i["kind"], i["status"]) for i in items] == [
        ("image", "extracted"), ("table", "extracted"), ("text", "extracted"), ("sheet", "extracted"),
        ("pdf", "extracted"), ("doc", "extracted"), ("doc", "extracted"),
    ]
    texts = [chunks_text(session, i["file_id"]) for i in items]
    assert texts[0] == "" and "골조" in texts[1] and "김하늘" in texts[2] and "타워크레인" in texts[3]
    assert "C24" in texts[4] and "골조 공사는 다음 주" in texts[5] and "7일 양생" in texts[6]


def test_get_raw_preview(client, admin):
    r = upload(client, admin, ("spec.pdf", fixture("spec.pdf")))["items"][0]
    got = client.get(f"/api/files/{r['file_id']}", headers=admin).json()
    assert got["kind"] == "pdf" and got["pages"] == 2 and got["size"] == len(fixture("spec.pdf"))
    assert got["deleted"] is False and got["axes"] == {}
    raw = client.get(f"/api/files/{r['file_id']}/raw", headers=admin)
    assert raw.content == fixture("spec.pdf") and raw.headers["content-type"] == "application/pdf"
    p2 = client.get(f"/api/files/{r['file_id']}/preview?page=2", headers=admin).json()
    assert p2["page"] == 2 and p2["pages"] == 2 and "Rebar" in p2["text"] and "C24" not in p2["text"]


def test_upload_to_someone_elses_chat_is_404(client, admin, user, chat_a):
    r = client.post("/api/files", files=[("files", ("a.txt", b"memo"))], data={"chat_id": str(chat_a)}, headers=user)
    assert r.status_code == 404


def test_delete_by_owner_or_admin_and_purge_admin_only(client, admin, user, session):
    mine = upload(client, user, ("a.txt", "내 메모".encode()))["items"][0]["file_id"]
    other = upload(client, admin, ("b.txt", "관리자 메모".encode()))["items"][0]["file_id"]
    assert client.delete(f"/api/files/{other}", headers=user).status_code == 403
    assert client.delete(f"/api/files/{mine}?purge=1", headers=user).status_code == 403
    assert client.delete(f"/api/files/{mine}", headers=user).status_code == 204
    assert client.get(f"/api/files/{mine}", headers=user).json()["deleted"] is True
    assert client.get(f"/api/files/{mine}/raw", headers=user).status_code == 404
    assert client.delete(f"/api/files/{other}?purge=1", headers=admin).status_code == 204
    assert client.get(f"/api/files/{other}", headers=admin).status_code == 404


# ── Fix round 1 ─────────────────────────────────────────────────────


def _scope(headers: dict[str, str]) -> dict:
    return {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/api/files", "raw_path": b"/api/files", "root_path": "", "query_string": b"",
        "server": ("testserver", 80), "client": ("testclient", 50000),
        "headers": [(k.encode(), v.encode()) for k, v in {"content-type": "multipart/form-data; boundary=b", **headers}.items()],
    }


async def _call_without_body(headers: dict[str, str]) -> int:
    """앱을 ASGI 로 바로 부른다. 몸을 읽으려 하면(receive) 실패한다."""
    from app.main import app

    async def receive():
        raise AssertionError("몸을 읽었다")

    sent = []

    async def send(message):
        sent.append(message)

    await app(_scope(headers), receive, send)
    return sent[0]["status"]


async def test_oversized_content_length_is_413_before_body():
    from app.security.tokens import issue_token

    token = issue_token(1)
    big = str(10 * 50 * 1024 * 1024 + 2 * 1024 * 1024)
    assert await _call_without_body({"authorization": f"Bearer {token}", "content-length": big}) == 413
    assert await _call_without_body({"authorization": f"Bearer {token}"}) == 411  # 길이 없음(chunked)


async def test_anonymous_upload_never_reads_body():
    assert await _call_without_body({"content-length": "100"}) == 401
    assert await _call_without_body({"authorization": "Bearer forged", "content-length": "100"}) == 401


def test_more_than_eleven_parts_is_refused_by_parser(client, admin):
    r = client.post("/api/files", files=[("files", (f"n{i}.txt", b"x")) for i in range(12)], headers=admin)
    assert r.status_code == 400


def test_soft_deleted_reupload_takes_new_owner(client, admin, user):
    fid = upload(client, admin, ("a.txt", "공용 메모".encode()))["items"][0]["file_id"]
    upload(client, user, ("b.txt", "공용 메모".encode()))  # 보이는 파일: 주인 그대로
    owner = client.get(f"/api/files/{fid}", headers=admin).json()["uploaded_by"]
    assert client.delete(f"/api/files/{fid}", headers=user).status_code == 403  # 아직 관리자 것
    assert client.delete(f"/api/files/{fid}", headers=admin).status_code == 204
    upload(client, user, ("b.txt", "공용 메모".encode()))  # 숨긴 파일: 다시 올린 사람이 주인
    got = client.get(f"/api/files/{fid}", headers=user).json()
    assert got["deleted"] is False and got["uploaded_by"] != owner
    assert client.delete(f"/api/files/{fid}", headers=user).status_code == 204


# ── Fix round 2 ─────────────────────────────────────────────────────


async def test_transfer_encoding_with_content_length_is_411_before_body():
    from app.security.tokens import issue_token

    auth_header = {"authorization": f"Bearer {issue_token(1)}"}
    both = {**auth_header, "content-length": "100", "transfer-encoding": "chunked"}
    assert await _call_without_body(both) == 411  # h11 은 chunked 를 따르므로 Content-Length 를 믿을 수 없다
    assert await _call_without_body({**auth_header, "content-length": "100", "transfer-encoding": "identity"}) == 411
