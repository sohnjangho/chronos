"""Liner Visualization 실측(Task 44 Step 0): 고정 가상 표로 `POST {base_url}/tools/visualization` 을 2번까지 부른다.

사용(저장소 루트에서, 앱 설정 환경 변수가 있는 셸):
    CHRONOS_DATA_DIR=$PWD/data backend/.venv/bin/python backend/scripts/probe_liner_visualization.py

- 요청 1: 기본(`stream` 생략 = SSE), 요청 2: `stream: false` — 문서에 없는 "한 덩어리 JSON 일 때 atlasArtifact 위치"를 본다.
  두 요청 모두 같은 표·같은 고정 틀, `is_search_context` 는 넣지 않는다.
- 키는 앱 코드(default_connection·decrypt)로 풀어 머리글에만 싣는다. 찍는 글·저장 파일에서 키와 키처럼 긴 토큰을 지운다.
  앱 DB 는 읽기 전용으로 연다(data/ 를 바꾸지 않는다).
- 찍는 것: 상태·종류·시간, 최상위 칸, theme·description·resourceId, HTML 길이, 외부 script/link 주소,
  표 값·날짜가 HTML 에 그대로 있는지, HTML 300자 발췌. 받은 HTML 은 OUT_DIR(환경 변수 CHRONOS_PROBE_OUT_DIR, 없으면 시스템 임시 폴더/visual-probe)에 저장한다.
"""

import asyncio
import json
import os
import re
import sys
import tempfile
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
TIMEOUT_S = 120.0
OUT_DIR = Path(os.environ.get("CHRONOS_PROBE_OUT_DIR", Path(tempfile.gettempdir()) / "visual-probe"))

# 가상 표: 작업 5개의 계획·전망 끝 날짜(실제 사업 자료 아님).
COLUMNS = ("작업", "계획 끝(YYYY-MM-DD)", "전망 끝(YYYY-MM-DD)")
ROWS = (
    ("터파기", "2027-03-12", "2027-03-15"),
    ("기초 타설", "2027-04-02", "2027-04-09"),
    ("골조 1층", "2027-05-07", "2027-05-14"),
    ("골조 2층", "2027-06-04", "2027-06-18"),
    ("지붕 방수", "2027-06-25", "2027-07-06"),
)
FRAME = (
    "아래 표의 값만 그대로 써서 작업별 계획 끝 날짜와 전망 끝 날짜를 비교하는 그림을 그려라. "
    "값을 계산·반올림·추정·추가하지 마라. 표에 없는 날짜나 값을 넣지 마라. "
    "작업 이름과 날짜(YYYY-MM-DD)는 표에 적힌 글자 그대로 쓴다.\n\n"
)
CALLS = (("1 SSE(기본)", {}), ("2 stream:false", {"stream": False}))
EXTERNAL = re.compile(r"""<(script|link)\b[^>]*?\b(src|href)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def table_csv() -> str:
    return "\n".join(",".join(row) for row in (COLUMNS, *ROWS))


def find_key(value: object, key: str) -> object:
    """중첩 dict/list 에서 처음 만나는 key 의 값을 찾는다(없으면 None)."""
    if isinstance(value, dict):
        if key in value:
            return value[key]
        value = list(value.values())
    if isinstance(value, list):
        for inner in value:
            found = find_key(inner, key)
            if found is not None:
                return found
    return None


class Probe:
    def __init__(self, base_url: str, key: str) -> None:
        self.url, self._key = f"{base_url}/tools/visualization", key
        self.sent = 0

    def scrub(self, text: str) -> str:
        """키와 키처럼 긴 토큰을 지운다(줄 모양은 그대로)."""
        return re.sub(r"[A-Za-z0-9_\-]{40,}", "…", text.replace(self._key, "…"))

    def clean(self, text: object, limit: int = 160) -> str:
        """지우고 한 줄로 자른다."""
        return re.sub(r"\s+", " ", self.scrub(str(text))).strip()[:limit]

    async def call(self, http: httpx.AsyncClient, label: str, extra: dict) -> None:
        if self.sent >= MAX_REQUESTS:
            raise SystemExit("요청 상한에 닿아 멈춘다.")
        self.sent += 1
        body = {"query": FRAME + table_csv(), **extra}
        start = time.perf_counter()
        try:
            r = await http.post(self.url, headers={"x-api-key": self._key, "Content-Type": "application/json"},
                                json=body)
        except httpx.HTTPError as e:
            print(f"[{label}] 통신 실패 {type(e).__name__} ({int((time.perf_counter() - start) * 1000)}ms)")
            return
        ms = int((time.perf_counter() - start) * 1000)
        kind = r.headers.get("content-type", "-")
        print(f"[{label}] HTTP {r.status_code} · {kind} · {ms}ms · {len(r.content)}B · 질의 {len(body['query'])}자")
        if r.status_code >= 400:
            retry = r.headers.get("retry-after")
            print(f"    본문: {self.clean(r.text, 300)}" + (f" · Retry-After {retry}" if retry else ""))
            return
        if "text/event-stream" in kind:
            data = self.read_sse(r.text)
        else:
            try:
                data = r.json()
            except ValueError:
                print(f"    본문(JSON 아님): {self.clean(r.text, 300)}")
                return
            print(f"    최상위 칸: {sorted(data) if isinstance(data, dict) else type(data).__name__}")
        self.show(label, data)

    def read_sse(self, text: str) -> list:
        """`data:` 줄을 JSON 으로 읽어 이벤트 목록을 돌려준다. 이벤트 순서와 data-atlas·data-error 칸을 찍는다."""
        events, kinds = [], []
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if raw == "[DONE]":
                kinds.append("[DONE]")
                continue
            try:
                event = json.loads(raw)
            except ValueError:
                kinds.append("(JSON 아님)")
                continue
            events.append(event)
            kinds.append(event.get("type", "?") if isinstance(event, dict) else type(event).__name__)
        print(f"    이벤트 {len(kinds)}개 순서: {kinds}")
        for event in events:
            if not isinstance(event, dict):
                continue
            if event.get("type") == "start":
                print(f"    start 칸: {sorted(event)} · trace_id={self.clean(find_key(event, 'trace_id'), 80)}")
            if event.get("type") in ("data-atlas", "data-error"):
                inner = event.get("data")
                print(f"    {event['type']} 최상위 칸: {sorted(event)} · data 칸: "
                      f"{sorted(inner) if isinstance(inner, dict) else type(inner).__name__}")
            if event.get("type") == "data-error":
                print(f"    data-error 본문: {self.clean(event, 300)}")
        return events

    def show(self, label: str, data: object) -> None:
        art = find_key(data, "atlasArtifact")
        if not isinstance(art, dict):
            print(f"    atlasArtifact 없음. 발췌: {self.clean(json.dumps(data, ensure_ascii=False), 400)}")
            return
        print(f"    atlasArtifact 칸: {sorted(art)}")
        for k in ("theme", "description", "resourceId"):
            print(f"    {k}: {self.clean(art.get(k), 300)}")
        html = art.get("html")
        if not isinstance(html, str):
            print(f"    html 없음/글 아님: {type(html).__name__}")
            return
        print(f"    html 길이: {len(html)}자")
        urls = [(tag.lower(), url) for tag, _, url in EXTERNAL.findall(html) if re.match(r"(https?:)?//", url)]
        print(f"    외부 주소 {len(urls)}개:")
        for tag, url in urls:
            print(f"      <{tag}> {self.clean(url, 300)}")
        found = total = 0
        for row in ROWS:
            marks = []
            for value in row:
                total += 1
                hit = value in html
                found += hit
                marks.append(f"{value}={'있음' if hit else '없음'}")
            print(f"      {' · '.join(marks)}")
        print(f"    표 값 그대로 있음: {found}/{total}")
        print(f"    발췌(300자): {self.clean(html, 300)}")
        name = "call1_sse.html" if label.startswith("1") else "call2_json.html"
        path = OUT_DIR / name
        path.write_text(self.scrub(html), encoding="utf-8")
        print(f"    저장: {path}")


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
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = Probe(base_url, key)
    print(f"표(CSV):\n{table_csv()}")
    async with httpx.AsyncClient(timeout=TIMEOUT_S, trust_env=False) as http:
        for i, (label, extra) in enumerate(CALLS):
            if i:
                await asyncio.sleep(1.0)  # 초당 2회 한도 — 차례로
            await p.call(http, label, extra)
    print(f"요청 수: {p.sent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
