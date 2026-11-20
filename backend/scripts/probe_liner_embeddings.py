"""Liner 임베딩 실측(Task 48 Step 0): `GET {base_url}/models` 1번, `POST {base_url}/embeddings` 1번(문장 2개).

사용(저장소 루트에서, 앱 설정 환경 변수가 있는 셸):
    CHRONOS_DATA_DIR=$PWD/data backend/.venv/bin/python backend/scripts/probe_liner_embeddings.py

- 요청은 2번까지(MAX_REQUESTS). 두 요청 사이 1초 쉰다.
- 키는 앱 코드(default_connection·decrypt)로 풀어 Authorization 머리글에만 싣는다. 찍는 글에서 키와
  키처럼 긴 토큰을 지운다. 앱 DB 는 읽기 전용으로 연다(data/ 를 바꾸지 않는다).
- 찍는 것: 상태·종류·시간, 최상위 칸, `/v1/embeddings` 를 지원하는 모델 이름들, MODEL 항목의 칸,
  임베딩 응답의 data 줄 수·벡터 값 종류·차원, usage 칸과 값.
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

MAX_REQUESTS = 2
TIMEOUT_S = 60.0
EMBED_ENDPOINT = "/v1/embeddings"
MODEL = "openai/text-embedding-3-small"
# 가상 문장 2개(실제 사업 자료 아님).
SENTENCES = ("동절기 콘크리트 타설은 보온 양생이 필요하다.", "겨울철 레미콘 작업은 얼지 않게 덮어 둔다.")


class Probe:
    def __init__(self, base_url: str, key: str) -> None:
        self.base_url, self._key = base_url, key
        self.sent = 0

    def clean(self, text: object, limit: int = 160) -> str:
        """키와 키처럼 긴 토큰을 지우고 한 줄로 자른다."""
        out = str(text).replace(self._key, "…")
        out = re.sub(r"[A-Za-z0-9_\-]{40,}", "…", out)
        return re.sub(r"\s+", " ", out).strip()[:limit]

    async def send(self, http: httpx.AsyncClient, label: str, method: str, path: str, body: dict | None) -> object:
        """한 번 보내고 JSON 본문(또는 None)을 돌려준다. 상태·종류·시간·크기를 찍는다."""
        if self.sent >= MAX_REQUESTS:
            raise SystemExit("요청 상한에 닿아 멈춘다.")
        self.sent += 1
        headers = {"Authorization": f"Bearer {self._key}", "Accept": "application/json"}
        start = time.perf_counter()
        try:
            r = await http.request(method, f"{self.base_url}{path}", headers=headers, json=body)
        except httpx.HTTPError as e:
            print(f"[{label}] 통신 실패 {type(e).__name__} ({int((time.perf_counter() - start) * 1000)}ms)")
            return None
        ms = int((time.perf_counter() - start) * 1000)
        kind = r.headers.get("content-type", "-")
        print(f"[{label}] HTTP {r.status_code} · {kind} · {ms}ms · {len(r.content)}B")
        if r.status_code >= 400:
            retry = r.headers.get("retry-after")
            print(f"    본문: {self.clean(r.text, 300)}" + (f" · Retry-After {retry}" if retry else ""))
            return None
        try:
            data = r.json()
        except ValueError:
            print(f"    본문(JSON 아님): {self.clean(r.text, 300)}")
            return None
        print(f"    최상위 칸: {sorted(data) if isinstance(data, dict) else type(data).__name__}")
        return data


def show_models(p: Probe, data: object) -> None:
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        print(f"    data 목록 없음: {p.clean(data, 300)}")
        return
    items = [row for row in rows if isinstance(row, dict) and "id" in row]
    with_endpoints = [row for row in items if isinstance(row.get("endpoints"), list)]
    embed = sorted(str(row["id"]) for row in with_endpoints if EMBED_ENDPOINT in row["endpoints"])
    print(f"    모델 {len(items)}개 · endpoints 칸 있음 {len(with_endpoints)}개")
    print(f"    {EMBED_ENDPOINT} 지원 {len(embed)}개:")
    for name in embed:
        print(f"      {name}")
    target = next((row for row in items if row["id"] == MODEL), None)
    if target is None:
        print(f"    {MODEL}: 목록에 없음")
        return
    print(f"    {MODEL} 칸: {sorted(target)}")
    print(f"      endpoints={target.get('endpoints')} context_length={target.get('context_length')}")


def show_embeddings(p: Probe, data: object) -> None:
    if not isinstance(data, dict):
        return
    print(f"    object={data.get('object')} model={p.clean(data.get('model'), 80)}")
    rows = data.get("data")
    if not isinstance(rows, list):
        print(f"    data 목록 없음: {p.clean(data, 300)}")
        return
    print(f"    data {len(rows)}줄")
    for row in rows:
        if not isinstance(row, dict):
            print(f"      줄 종류: {type(row).__name__}")
            continue
        vec = row.get("embedding")
        size = len(vec) if isinstance(vec, list) else None
        kind = type(vec[0]).__name__ if isinstance(vec, list) and vec else type(vec).__name__
        print(f"      칸 {sorted(row)} · index={row.get('index')} · 값 종류 {kind} · 차원 {size}")
    usage = data.get("usage")
    print(f"    usage: {json.dumps(usage, ensure_ascii=False) if isinstance(usage, dict) else p.clean(usage)}")


def target() -> tuple[str, str]:
    db = Settings().data_dir.resolve() / "chronos.db"
    engine = create_engine(f"sqlite:///file:{db}?mode=ro&uri=true")
    with Session(engine) as session:
        conn = default_connection(session)
        if conn is None or conn.provider != "liner":
            raise SystemExit("기본 Liner 연결이 없다. 멈춘다.")
        print(f"연결: {conn.name} (id={conn.id}, host={httpx.URL(conn.base_url).host})")
        return conn.base_url.rstrip("/"), decrypt(conn.secret_ciphertext)


async def main() -> int:
    base_url, key = target()
    p = Probe(base_url, key)
    print(f"모델: {MODEL} · 문장 {len(SENTENCES)}개: {list(SENTENCES)}")
    async with httpx.AsyncClient(timeout=TIMEOUT_S, trust_env=False) as http:
        show_models(p, await p.send(http, "1 GET /models", "GET", "/models", None))
        await asyncio.sleep(1.0)  # 차례로
        body = {"model": MODEL, "input": list(SENTENCES)}
        show_embeddings(p, await p.send(http, "2 POST /embeddings", "POST", "/embeddings", body))
    print(f"요청 수: {p.sent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
