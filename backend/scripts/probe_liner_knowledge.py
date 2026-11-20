"""Liner Search 프리미엄 자료 실측(Task 45 Step 0): `include_knowledge: true` 웹 검색을 2번까지 하고 `knowledge` 모양을 찍는다.

사용(저장소 루트에서, 앱 설정 환경 변수가 있는 셸):
    CHRONOS_DATA_DIR=$PWD/data backend/.venv/bin/python backend/scripts/probe_liner_knowledge.py

- 요청: `POST {base_url}/tools/search/web`, 머리글 `x-api-key`, 본문 `{query, max_results: 3, include_knowledge: true}`.
- 키는 앱 코드(default_connection·decrypt)로 풀어 머리글에만 싣는다. 찍는 글에서는 키와 키처럼 긴 토큰을 지운다.
  앱 DB 는 읽기 전용으로 연다(data/ 를 바꾸지 않는다).
- 찍는 것: 상태·시간·응답 최상위 칸·results 수, 그리고 knowledge 의 모양(종류·칸·목록 길이, 깊이 4까지)과 첫 항목 발췌.
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
QUERIES = ("서울 12월 평균 기온 강수일", "철근 가격 추이 2026")
DEPTH = 4


class Probe:
    def __init__(self, base_url: str, key: str) -> None:
        self.url, self._key = f"{base_url}/tools/search/web", key
        self.sent = 0

    def clean(self, text: object, limit: int = 160) -> str:
        """키와 키처럼 긴 토큰을 지우고 한 줄로 자른다."""
        out = str(text).replace(self._key, "…")
        out = re.sub(r"[A-Za-z0-9_\-]{40,}", "…", out)
        return re.sub(r"\s+", " ", out).strip()[:limit]

    async def search(self, http: httpx.AsyncClient, query: str) -> object:
        if self.sent >= MAX_REQUESTS:
            raise SystemExit("요청 상한에 닿아 멈춘다.")
        self.sent += 1
        start = time.perf_counter()
        try:
            r = await http.post(self.url, headers={"x-api-key": self._key, "Content-Type": "application/json"},
                                json={"query": query, "max_results": 3, "include_knowledge": True})
        except httpx.HTTPError as e:
            print(f"[{self.sent}] {query!r}: 통신 실패 {type(e).__name__} ({int((time.perf_counter() - start) * 1000)}ms)")
            return None
        ms = int((time.perf_counter() - start) * 1000)
        print(f"[{self.sent}] {query!r}: HTTP {r.status_code} · {r.headers.get('content-type', '-')} · {ms}ms · "
              f"{len(r.content)}B")
        try:
            data = r.json()
        except ValueError:
            print(f"    본문(JSON 아님): {self.clean(r.text, 300)}")
            return None
        if r.status_code >= 400:
            print(f"    본문: {self.clean(data, 300)}")
            return None
        return data

    def shape(self, value: object, name: str, depth: int = 0) -> None:
        """값의 모양을 들여 찍는다: dict 는 칸마다, list 는 길이와 첫 항목, 글·숫자는 종류와 발췌."""
        pad = "    " + "  " * depth
        if isinstance(value, dict):
            print(f"{pad}{name}: 객체 칸 {sorted(value)}")
            if depth < DEPTH:
                for key, inner in value.items():
                    self.shape(inner, key, depth + 1)
        elif isinstance(value, list):
            kinds = sorted({type(v).__name__ for v in value})
            print(f"{pad}{name}: 목록 {len(value)}개 (항목 종류 {kinds})")
            if value and depth < DEPTH:
                self.shape(value[0], f"{name}[0]", depth + 1)
        else:
            print(f"{pad}{name}: {type(value).__name__} = {self.clean(value, 80)}")

    def show(self, data: object) -> None:
        if not isinstance(data, dict):
            print(f"    응답이 객체가 아님: {self.clean(data, 200)}")
            return
        print(f"    최상위 칸: {sorted(data)}")
        results = data.get("results")
        print(f"    results: {len(results) if isinstance(results, list) else '없음'}줄")
        if "knowledge" not in data:
            print("    knowledge 칸 없음")
            return
        knowledge = data["knowledge"]
        self.shape(knowledge, "knowledge")
        first = knowledge[0] if isinstance(knowledge, list) and knowledge else knowledge
        print(f"    knowledge 첫 항목 발췌: {self.clean(json.dumps(first, ensure_ascii=False), 800)}")


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
    async with httpx.AsyncClient(timeout=TIMEOUT_S, trust_env=False) as http:
        for query in QUERIES:
            p.show(await p.search(http, query))
    print(f"요청 수: {p.sent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
