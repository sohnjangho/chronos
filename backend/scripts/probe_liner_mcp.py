"""Liner MCP 실측(Task 27b Step 0): 기본 연결의 키로 `{base_url}/mcp` 를 5번까지 부르고 응답 모양을 찍는다.

사용(backend 폴더에서, 앱 설정 환경 변수가 있는 셸):
    .venv/bin/python scripts/probe_liner_mcp.py

순서: initialize → notifications/initialized → tools/list → tools/call search_legal → tools/call search_business.
- Streamable HTTP: JSON-RPC 2.0 POST, `Accept: application/json, text/event-stream`. 응답이 SSE 면 `data:` 줄을 읽는다.
- 키는 앱 코드(default_connection·decrypt)로 풀어 Authorization 머리글에만 싣는다. 찍는 글에서는 키와
  키처럼 긴 토큰을 지운다. 앱 DB 는 읽기 전용으로 연다(data/ 를 바꾸지 않는다).
"""

import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 앱 패키지(app)를 찾게 한다

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.llm.assignments import default_connection
from app.security.crypto import decrypt

MAX_REQUESTS = 5
TIMEOUT_S = 60.0
PROTOCOL = "2025-06-18"
CALLS = (("search_legal", "건축물 착공신고 처리 기한"), ("search_business", "철근 공급업체 납기"))


class Probe:
    def __init__(self, url: str, key: str) -> None:
        self.url, self._key = url, key
        self.session_id: str | None = None
        self.protocol: str | None = None
        self.sent = 0

    def clean(self, text: object, limit: int = 160) -> str:
        """키와 키처럼 긴 토큰을 지우고 한 줄로 자른다."""
        out = str(text).replace(self._key, "…")
        out = re.sub(r"[A-Za-z0-9_\-]{40,}", "…", out)
        return re.sub(r"\s+", " ", out).strip()[:limit]

    def headers(self) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self._key}", "Accept": "application/json, text/event-stream",
             "Content-Type": "application/json"}
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        if self.protocol:
            h["MCP-Protocol-Version"] = self.protocol
        return h

    async def post(self, http: httpx.AsyncClient, label: str, payload: dict) -> object:
        """한 번 보내고 JSON-RPC 응답(dict) 또는 None 을 돌려준다. 상태·종류·시간을 찍는다."""
        if self.sent >= MAX_REQUESTS:
            raise SystemExit("요청 상한에 닿아 멈춘다.")
        self.sent += 1
        start = time.perf_counter()
        try:
            r = await http.post(self.url, headers=self.headers(), json=payload)
        except httpx.HTTPError as e:
            print(f"[{self.sent}] {label}: 통신 실패 {type(e).__name__} ({int((time.perf_counter() - start) * 1000)}ms)")
            return None
        ms = int((time.perf_counter() - start) * 1000)
        kind = r.headers.get("content-type", "-")
        sid = "있음" if r.headers.get("mcp-session-id") else "없음"
        print(f"[{self.sent}] {label}: HTTP {r.status_code} · {kind} · {ms}ms · Mcp-Session-Id {sid} · {len(r.content)}B")
        if r.headers.get("mcp-session-id"):
            self.session_id = r.headers["mcp-session-id"]
        if not r.content:
            return None
        message = read_message(r.text, kind)
        if r.status_code >= 400 or message is None:
            print(f"    본문: {self.clean(r.text, 300)}")
        return message


def read_message(text: str, kind: str) -> object:
    if "text/event-stream" in kind:
        datas = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        for raw in reversed(datas):
            try:
                found = json.loads(raw)
            except ValueError:
                continue
            if isinstance(found, dict) and ("result" in found or "error" in found):
                return found
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def show_initialize(p: Probe, msg: object) -> bool:
    if not isinstance(msg, dict) or "result" not in msg:
        print(f"    initialize 실패: {p.clean(msg, 300)}")
        return False
    res = msg["result"]
    p.protocol = res.get("protocolVersion") or PROTOCOL
    print(f"    protocolVersion={res.get('protocolVersion')} serverInfo={p.clean(res.get('serverInfo'))}")
    print(f"    capabilities={sorted(res.get('capabilities') or {})}")
    return True


def show_tools(p: Probe, msg: object) -> None:
    tools = msg.get("result", {}).get("tools") if isinstance(msg, dict) else None
    if not isinstance(tools, list):
        print(f"    tools/list 읽지 못함: {p.clean(msg, 300)}")
        return
    print(f"    도구 {len(tools)}개: {[t.get('name') for t in tools]}")
    for t in tools:
        if t.get("name") in dict(CALLS):
            schema = t.get("inputSchema") or {}
            print(f"    - {t['name']}: props={sorted(schema.get('properties') or {})} required={schema.get('required')}")
            print(f"      설명: {p.clean(t.get('description'), 200)}")
            if t.get("outputSchema"):
                print(f"      outputSchema props={sorted(t['outputSchema'].get('properties') or {})}")


def show_shape(p: Probe, data: object, where: str) -> None:
    if isinstance(data, dict):
        print(f"    {where} 칸: {sorted(data)}")
        for key in ("results", "items", "data"):
            rows = data.get(key)
            if isinstance(rows, list):
                print(f"    {where}.{key}: {len(rows)}줄")
                if rows and isinstance(rows[0], dict):
                    first = rows[0]
                    print(f"    첫 줄 칸: {sorted(first)}")
                    for k in ("title", "url", "date", "description"):
                        if k in first:
                            print(f"      {k}: {p.clean(first[k], 100)}")
    elif isinstance(data, list):
        print(f"    {where}: 목록 {len(data)}줄, 첫 줄 {p.clean(data[:1], 200)}")
    else:
        print(f"    {where}: {p.clean(data, 200)}")


def show_call(p: Probe, msg: object) -> None:
    if not isinstance(msg, dict):
        print("    응답 없음")
        return
    if "error" in msg:
        print(f"    JSON-RPC 오류: {p.clean(msg['error'], 300)}")
        return
    res = msg.get("result") or {}
    print(f"    result 칸: {sorted(res)} isError={res.get('isError')}")
    for i, item in enumerate(res.get("content") or []):
        kind = item.get("type") if isinstance(item, dict) else type(item).__name__
        text = item.get("text") if isinstance(item, dict) else None
        print(f"    content[{i}] type={kind} 글 {len(text or '')}자")
        if isinstance(text, str):
            try:
                show_shape(p, json.loads(text), f"content[{i}] JSON")
            except ValueError:
                print(f"      글: {p.clean(text, 200)}")
    if "structuredContent" in res:
        show_shape(p, res["structuredContent"], "structuredContent")


def target() -> tuple[str, str]:
    db = Settings().data_dir.resolve() / "chronos.db"
    engine = create_engine(f"sqlite:///file:{db}?mode=ro&uri=true")
    with Session(engine) as session:
        conn = default_connection(session)
        if conn is None or conn.provider != "liner":
            raise SystemExit("기본 Liner 연결이 없다. 멈춘다.")
        print(f"연결: {conn.name} (id={conn.id}, host={httpx.URL(conn.base_url).host})")
        return conn.base_url.rstrip("/") + "/mcp", decrypt(conn.secret_ciphertext)


async def main() -> int:
    url, key = target()
    p = Probe(url, key)
    print(f"MCP 주소: {url}")
    async with httpx.AsyncClient(timeout=TIMEOUT_S, trust_env=False) as http:
        init = await p.post(http, "initialize", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": PROTOCOL, "capabilities": {},
            "clientInfo": {"name": "chronos-probe", "version": "0.1"}}})
        if not show_initialize(p, init):
            return 1
        await p.post(http, "notifications/initialized", {"jsonrpc": "2.0", "method": "notifications/initialized"})
        show_tools(p, await p.post(http, "tools/list", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
        for i, (name, query) in enumerate(CALLS, 3):
            msg = await p.post(http, f"tools/call {name}", {"jsonrpc": "2.0", "id": i, "method": "tools/call",
                                                          "params": {"name": name, "arguments": {"query": query}}})
            show_call(p, msg)
    print(f"요청 수: {p.sent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
