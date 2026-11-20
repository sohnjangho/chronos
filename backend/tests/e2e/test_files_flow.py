"""서버 끝에서 끝까지(계획 3): 파일 올리기 · 자료함 찾기/미리 보기/축 고치기 · 대화 첨부 · 모델 고르기 · 정보 API."""

import io
import json

import pytest

from app.llm import fake
from tests.llm_doubles import add_connection


@pytest.fixture
def env(session, monkeypatch):
    monkeypatch.setenv(fake.ENV, "1")
    conn = add_connection(session)
    conn.models_json = json.dumps([
        {
            "id": "liner-mark",
            "name": "Liner Mark",
            "vendor": "liner",
            "vendor_name": "Liner",
            "context_length": 1000000,
            "chat": True,
            "embedding": False,
            "price": None,
        }
    ])
    session.commit()
    return conn


def _ok(r, status: int = 200):
    assert r.status_code == status, r.text
    return r.json() if status != 204 else None


def _login(client) -> dict[str, str]:
    token = _ok(client.post("/api/auth/login", json={"login_id": "admin", "password": "test-pass"}))["token"]
    return {"Authorization": f"Bearer {token}"}


def _events(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.strip().split("\n\n"):
        if not block or block.startswith(":"):
            continue
        lines = block.split("\n")
        if len(lines) >= 2:
            out.append((lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))))
    return out


def test_plan3_files_chat_model_and_info_api_flow(client, env):
    h = _login(client)

    # 1. 파일 올리기(텍스트 시방서 + CSV 표)
    spec_bytes = "동절기 콘크리트 타설 기준: 외기온도 4도 이하일 때 한중 콘크리트 양생 적용.\n".encode("utf-8")
    csv_bytes = "ID,작업명,기간\nA10,가설,5\nA20,토공,10\n".encode("utf-8")
    uploaded = _ok(
        client.post(
            "/api/files",
            files=[
                ("files", ("동절기_시방서.txt", io.BytesIO(spec_bytes), "text/plain")),
                ("files", ("공정표_초안.csv", io.BytesIO(csv_bytes), "text/csv")),
            ],
            headers=h,
        )
    )
    assert len(uploaded["items"]) == 2
    spec_id = uploaded["items"][0]["file_id"]
    csv_id = uploaded["items"][1]["file_id"]

    # 2. 자료함 목록 · 찾기(낱말) · 미리 보기 · 축 고치기
    listed = _ok(client.get("/api/files", params={"q": "한중 콘크리트"}, headers=h))
    assert any(f["file_id"] == spec_id for f in listed["items"])

    preview = _ok(client.get(f"/api/files/{spec_id}/preview", params={"page": 1}, headers=h))
    assert "한중 콘크리트" in preview["text"]

    patched = _ok(client.patch(f"/api/files/{spec_id}/axes", json={"종류": ["시방서"], "공종": ["골조"]}, headers=h))
    assert patched["axes"]["종류"] == ["시방서"]
    assert patched["axes"]["공종"] == ["골조"]

    axes = _ok(client.get("/api/files/axes", headers=h))
    assert any(v["value"] == "시방서" and v["count"] >= 1 for v in axes["종류"])

    # 3. 대화 생성 · 대화 모델 고르기(PUT/DELETE) · 파일 붙여 메시지 보내기
    chat = _ok(client.post("/api/chat/sessions", json={}, headers=h))
    chat_id = chat["id"]

    models = _ok(client.get("/api/llm/models", params={"for": "chat"}, headers=h))
    first_conn = models["connections"][0]
    first_model = first_conn["models"][0]["id"]
    set_res = _ok(
        client.put(
            f"/api/chat/sessions/{chat_id}/model",
            json={"connection_id": first_conn["connection_id"], "model": first_model, "routing_strategy": None},
            headers=h,
        )
    )
    assert set_res["model"] == first_model

    r = client.post(
        f"/api/chat/sessions/{chat_id}/messages",
        json={"text": "붙인 파일을 봐 주세요.", "file_ids": [spec_id, csv_id], "ui": {}},
        headers=h,
    )
    assert r.status_code == 200, r.text
    evs = _events(r.text)
    assert any(t in ("text", "done") for t, _ in evs)

    detail = _ok(client.get(f"/api/chat/sessions/{chat_id}", headers=h))
    assert detail["model"]["model"] == first_model
    assert [f["file_id"] for f in detail["files"]] == [spec_id, csv_id]

    _ok(client.delete(f"/api/chat/sessions/{chat_id}/model", headers=h), status=204)
    detail2 = _ok(client.get(f"/api/chat/sessions/{chat_id}", headers=h))
    assert detail2["model"] is None

    # 4. 정보 API 연결(기상청) 저장 및 끝 4자리 확인
    conn_out = _ok(
        client.post(
            "/api/info/connections",
            json={"name": "기상청 공공데이터", "preset": "kma", "secret": "fake-kma-key-9876"},
            headers=h,
        ),
        status=201,
    )
    assert conn_out["secret_last4"] == "9876"
    assert "fake-kma-key" not in json.dumps(conn_out)

    # 5. 자료 지우기(숨김) 확인
    _ok(client.delete(f"/api/files/{csv_id}", headers=h), status=204)
    detail3 = _ok(client.get(f"/api/chat/sessions/{chat_id}", headers=h))
    csv_entry = next(f for f in detail3["files"] if f["file_id"] == csv_id)
    assert csv_entry["deleted"] is True
