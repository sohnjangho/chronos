"""Liner 실측(Checkpoint A): 앱의 LlmClient 와 기본 연결로 실제 API 를 몇 번 부르고 결과를 표로 찍는다.

사용(실행 중인 backend 컨테이너 안):
    docker compose exec -T backend python scripts/probe_liner.py [--only CHECK] [--list]
    CHECK: tools · tools_real · json · routing · routing_cpm · image (여러 번 줄 수 있다)

- 요청 본문은 앱 client 가 만든다. 모델·routing_strategy 만 바꾸고(배정을 저장하지 않는다),
  예산 때문에 max_tokens 를 더한다(앱 client 는 max_tokens 를 보내지 않는다).
- 키는 앱 client 가 Authorization 머리글에만 싣는다. 이 스크립트는 키·요청 머리글을 보지 않는다.
- 앱 DB 는 읽기 전용으로 연다. llm_calls 기록은 메모리 DB 로 보낸다(data/ 를 바꾸지 않는다).
- 모델 출력은 120자까지만 찍는다. 실패는 HTTP 상태와 제공자 오류 코드·메시지(잘라서)만 찍는다.
"""

import argparse
import asyncio
import base64
import json
import re
import struct
import sys
import time
import zlib
from dataclasses import dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 앱 패키지(app)를 찾게 한다

import httpx
from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.generation_steps import REPAIR_SCHEMA, strict_object
from app.config import Settings
from app.llm.assignments import default_connection, resolve
from app.llm.client import LlmClient, LlmFailed, LlmReply
from app.store.tables import LlmCall
from app.tools import registry
from app.tools.context import ToolContext
from app.tools.generate.extract_conditions import EXTRACT_SCHEMA

MAX_CALLS = 25
PAUSE_S = 2.0
EXCERPT = 120
MARK, CLAUDE, GPT, GEMINI = "liner-mark", "liner-claude-router", "liner-gpt-router", "liner-gemini-router"
CHECKS = ("tools", "tools_real", "json", "routing", "routing_cpm", "image")
SIMPLE_SCHEMA = strict_object(
    {"title": {"type": "string"}, "workdays": {"type": "integer"}, "outdoor": {"type": "boolean"}}
)
_DROP_HEADERS = {"content-encoding", "content-length", "transfer-encoding"}


class AddIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    a: int
    b: int


class AddOut(BaseModel):
    sum: int


def add(args: AddIn, ctx: ToolContext) -> AddOut:
    return AddOut(sum=args.a + args.b)


class Tap(httpx.AsyncBaseTransport):
    """실제 전송을 감싸 마지막 응답의 상태·본문(JSON)만 잡아 둔다. 요청 머리글은 보지 않는다."""

    def __init__(self) -> None:
        self.calls = 0
        self.status: int | None = None
        self.body: object = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.status, self.body = None, None
        async with httpx.AsyncHTTPTransport() as inner:
            response = await inner.handle_async_request(request)
            content = await response.aread()
            await response.aclose()
        self.status = response.status_code
        try:
            self.body = json.loads(content)
        except ValueError:
            self.body = None
        headers = [(k, v) for k, v in response.headers.items() if k.lower() not in _DROP_HEADERS]
        return httpx.Response(response.status_code, headers=headers, content=content, request=request)


class ProbeClient(LlmClient):
    """앱 client 그대로 부르되 모델·routing_strategy 를 바꾸고 max_tokens 를 더한다."""

    def __init__(self, session: Session, tap: Tap, model: str, strategy: str | None, max_tokens: int):
        super().__init__(session, transport=tap)
        self._model, self._strategy, self._max_tokens = model, strategy, max_tokens

    def _target(self, purpose):
        return replace(super()._target(purpose), model=self._model, routing_strategy=self._strategy)

    async def _post(self, target, body, timeout_s):
        return await super()._post(target, {**body, "max_tokens": self._max_tokens}, timeout_s)


@dataclass(frozen=True)
class Case:
    check: str
    model: str
    strategy: str | None
    messages: list[dict]
    tools: list[dict] | None = None
    schema: dict | None = None
    max_tokens: int = 300


def short(text: object, limit: int = EXCERPT) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()[:limit]


def redact(text: str) -> str:
    """제공자 오류 글에서 키처럼 긴 토큰을 지우고 자른다."""
    return short(re.sub(r"[A-Za-z0-9_\-]{24,}", "…", text), 160)


def provider_error(body: object) -> str:
    if not isinstance(body, dict):
        return "(본문 JSON 아님)"
    err = body.get("error", body)
    if not isinstance(err, dict):
        return redact(str(err))
    head = " ".join(str(err[k]) for k in ("code", "type") if err.get(k))
    return redact(f"{head} {err.get('message') or err.get('detail') or ''}")


def tiny_png() -> str:
    """8×8 단색(파랑) PNG 의 data URI."""
    rows = b"".join(b"\x00" + bytes((30, 90, 220)) * 8 for _ in range(8))

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode()


_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def schema_errors(schema: dict, value: object, path: str = "$") -> list[str]:
    """우리 strict 스키마에 쓰는 만큼만(type·enum·anyOf·properties·required·additionalProperties·items)."""
    if "anyOf" in schema:
        return [] if any(not schema_errors(s, value, path) for s in schema["anyOf"]) else [f"{path}: anyOf"]
    types = schema.get("type")
    types = [types] if isinstance(types, str) else types or []
    if types and not any(_TYPES[t](value) for t in types):
        return [f"{path}: type {types}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: enum"]
    out: list[str] = []
    if isinstance(value, dict):
        props = schema.get("properties", {})
        out += [f"{path}.{k}: 빠짐" for k in schema.get("required", []) if k not in value]
        if schema.get("additionalProperties") is False:
            out += [f"{path}.{k}: 모르는 칸" for k in value if k not in props]
        for k, v in value.items():
            if k in props:
                out += schema_errors(props[k], v, f"{path}.{k}")
    elif isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            out += schema_errors(schema["items"], v, f"{path}[{i}]")
    return out


def llm_tools() -> tuple[list[dict], list[dict]]:
    """(작은 도구 calc__add 하나, 앱의 실제 도구 전부). 둘 다 registry.as_llm_tools() 모양."""
    registry.tool("calc.add", "두 정수 a, b 를 더한다.")(add)
    registry.load_all()
    tools = registry.as_llm_tools()
    tiny = [t for t in tools if t["function"]["name"] == "calc__add"]
    return tiny, [t for t in tools if t["function"]["name"] != "calc__add"]


def _user(text: str, system: str | None = None) -> list[dict]:
    head = [{"role": "system", "content": system}] if system else []
    return [*head, {"role": "user", "content": text}]


EXTRACT_SYSTEM = (
    "일정 요청에서 입력 조건(conditions)·사실(facts)·가정(assumptions)·모르는 것(unknown)을 뽑는다. "
    "조건 종류에 쓰지 않는 칸은 null. 날짜는 YYYY-MM-DD, start_md·end_md 는 [월, 일]."
)
EXTRACT_USER = (
    "가상의 '푸른숲 도서관' 리모델링. 2027-03-02 이후 착공, 2027-08-31 까지 준공. 주 5일 근무. "
    "7월 1일~8월 15일에는 outdoor 꼬리표 작업 금지. 크레인(crane)은 1대뿐."
)
REPAIR_SYSTEM = "일정 고침 단계. WBS 를 바꾸지 않으면 wbs 는 null. 날짜는 내지 않고 기간(od, 근무일)과 선후 관계만 낸다."
REPAIR_USER = (
    "가상 일정 '푸른숲 도서관 리모델링'의 액티비티를 고쳐라. WBS 는 그대로 둔다. 액티비티 3개: "
    "A1 착공(start_ms, od 0), A2 내부 철거(task, 5일, A1 뒤 FS lag 0), A3 준공(finish_ms, od 0, A2 뒤 FS lag 0). "
    "wbs 코드는 모두 W1, tags 는 빈 목록."
)


def build_cases() -> list[Case]:
    tiny, real = llm_tools()
    add_msg = _user("17 더하기 25 를 calc__add 도구로 계산하라. 직접 계산하지 말고 반드시 도구를 불러라.")
    real_msg = _user(
        "가상 일정 '푸른숲 도서관 리모델링'의 현재 상태 요약을 읽어 줘.",
        "너는 일정 관리 에이전트다. 필요하면 도구를 부른다.",
    )
    simple = _user("가상의 '푸른숲 도서관 리모델링' 공사를 한 줄 제목, 예상 근무일 수, 외부 작업 여부로 요약하라.")
    extract = _user(EXTRACT_USER, EXTRACT_SYSTEM)
    repair = _user(REPAIR_USER, REPAIR_SYSTEM)
    sky = _user("한 단어로 답하라: 맑은 날 하늘의 색은?")
    cpm = _user(
        "가상 일정: A(5일) 뒤 B(3일), A 뒤 C(7일), B 와 C 가 모두 끝나면 D(2일). "
        "주공정과 총 기간을 근거와 함께 세 줄로 답하라."
    )
    image = [{"role": "user", "content": [
        {"type": "text", "text": "이 그림은 한 가지 색으로 칠해져 있다. 그 색을 한 단어로 답하라."},
        {"type": "image_url", "image_url": {"url": tiny_png()}},
    ]}]
    cases = [Case("tools", MARK, None, add_msg, tiny)]
    cases += [Case("tools", m, "balanced", add_msg, tiny) for m in (CLAUDE, GPT, GEMINI)]
    cases += [Case("tools_real", MARK, None, real_msg, real)]
    cases += [Case("tools_real", m, "balanced", real_msg, real) for m in (CLAUDE, GPT, GEMINI)]
    for model, strategy in ((CLAUDE, "quality"), (MARK, None)):
        cases += [
            Case("json", model, strategy, simple, schema=SIMPLE_SCHEMA),
            Case("json", model, strategy, extract, schema=EXTRACT_SCHEMA, max_tokens=1200),
            Case("json", model, strategy, repair, schema=REPAIR_SCHEMA, max_tokens=1200),
        ]
    cases += [Case("routing", CLAUDE, s, sky) for s in ("cost", "balanced", "quality")]
    cases += [Case("routing_cpm", CLAUDE, s, cpm) for s in ("cost", "balanced", "quality")]
    cases += [Case("image", m, s, image) for m, s in ((MARK, None), (CLAUDE, "balanced"))]
    return cases


def schema_name(case: Case) -> str:
    names = {id(SIMPLE_SCHEMA): "simple", id(EXTRACT_SCHEMA): "EXTRACT", id(REPAIR_SCHEMA): "REPAIR"}
    return names.get(id(case.schema), "")


def judge(case: Case, reply: LlmReply) -> tuple[str, str]:
    """(결과, 메모)."""
    calls = reply.tool_calls
    if case.check == "tools":
        if not calls:
            return "NO_CALL", "도구 호출 없음"
        c = calls[0]
        ok = c.name == "calc.add" and isinstance(c.arguments, dict) and set(c.arguments) == {"a", "b"}
        return ("OK" if ok else "BAD_ARGS"), f"{c.name} {short(c.arguments or c.raw_arguments, 60)}"
    if case.check == "tools_real":
        if not calls:
            return "OK", "요청 받음, 도구 호출 없음(글 답)"
        parsed = all(isinstance(c.arguments, dict) for c in calls)
        return "OK", f"{', '.join(c.name for c in calls)} 인자 {'읽힘' if parsed else '못 읽음'}"
    if case.schema is not None:
        if reply.parsed is None:
            return "NOT_JSON", schema_name(case)
        errs = schema_errors(case.schema, reply.parsed)
        return ("OK" if not errs else "INVALID"), f"{schema_name(case)} " + ("; ".join(errs[:2]) or "스키마 맞음")
    return "OK", ""


@dataclass
class Row:
    case: Case
    result: str
    note: str
    excerpt: str
    ms: int
    status: int | None
    returned: str = "-"
    finish: str = "-"
    usage: dict | None = None
    top_keys: tuple[str, ...] = ()


def meta(row: Row, body: object) -> None:
    if not isinstance(body, dict):
        return
    row.returned = str(body.get("model", "-"))
    row.top_keys = tuple(sorted(body))
    row.usage = body.get("usage") if isinstance(body.get("usage"), dict) else None
    choices = body.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        row.finish = str(choices[0].get("finish_reason", "-"))


async def run_case(session: Session, tap: Tap, case: Case) -> Row:
    client = ProbeClient(session, tap, case.model, case.strategy, case.max_tokens)
    start = time.perf_counter()
    try:
        reply = await client.chat("normal", case.messages, tools=case.tools, json_schema=case.schema, timeout_s=180)
    except LlmFailed as e:
        ms = int((time.perf_counter() - start) * 1000)
        note = f"HTTP {tap.status} {e.error.code}: {provider_error(tap.body)}"
        row = Row(case, "FAIL", note, "", ms, tap.status)
    else:
        ms = int((time.perf_counter() - start) * 1000)
        result, note = judge(case, reply)
        row = Row(case, result, note, short(reply.text), ms, tap.status)
    meta(row, tap.body)
    return row


def open_session() -> Session:
    """앱 DB 는 읽기 전용, llm_calls 기록은 메모리 DB 로."""
    db = Settings().data_dir.resolve() / "chronos.db"
    app_db = create_engine(f"sqlite:///file:{db}?mode=ro&uri=true")
    memory = create_engine("sqlite://")
    LlmCall.__table__.create(memory)
    return Session(bind=app_db, binds={LlmCall: memory})


def preflight(session: Session) -> bool:
    conn = default_connection(session)
    target = resolve(session, "normal")
    if conn is None or target.connection_id != conn.id:
        print("기본 연결이 없거나 normal 배정이 기본 연결을 가리키지 않는다. 멈춘다.")
        return False
    host = httpx.URL(conn.base_url).host
    print(f"연결: {conn.name} (id={conn.id}, host={host}, status={conn.status}, 모델 {conn.model_count}개)")
    return True


def print_row(i: int, row: Row) -> None:
    c = row.case
    model = c.model + (f"/{c.strategy}" if c.strategy else "")
    u = row.usage or {}
    cost = u.get("cost", "-")
    print(
        f"{i:>2} {c.check:<11} {model:<29} {row.result:<8} ret={row.returned} "
        f"tok={u.get('prompt_tokens', '-')}/{u.get('completion_tokens', '-')} cost={cost} "
        f"{row.ms}ms fin={row.finish} | {row.note}"
    )
    if row.excerpt:
        print(f"   > {row.excerpt}")


def summary(rows: list[Row], tap: Tap, session: Session) -> None:
    print(f"\nAPI 호출 수: {tap.calls}")
    keys = sorted({k for r in rows if r.usage for k in r.usage})
    print(f"usage 칸: {keys}")
    print(f"응답 최상위 칸: {sorted({k for r in rows for k in r.top_keys})}")
    seen: set[str] = set()
    for r in rows:
        if r.usage and r.case.model not in seen:
            seen.add(r.case.model)
            print(f"usage 예 {r.case.model}: {short(json.dumps(r.usage, ensure_ascii=False), 300)}")
    routing = [f"{r.case.check}/{r.case.strategy}→{r.returned}" for r in rows if r.case.check.startswith("routing")]
    if routing:
        print(f"routing ({CLAUDE}): {', '.join(routing)}")
    recorded = session.scalars(select(LlmCall).order_by(LlmCall.id)).all()
    ok = sum(1 for r in recorded if r.ok)
    costs = [r.cost for r in recorded if r.cost is not None]
    print(f"llm_calls(메모리 기록): {len(recorded)}줄, ok {ok}, cost 있는 줄 {len(costs)}, 합 {sum(costs):.6f}")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", action="append", choices=CHECKS, help="이 검사만(여러 번 가능)")
    parser.add_argument("--list", action="store_true", help="보내지 않고 할 일만 찍는다")
    args = parser.parse_args()
    cases = [c for c in build_cases() if not args.only or c.check in args.only]
    if args.list:
        for i, c in enumerate(cases, 1):
            print(f"{i:>2} {c.check:<11} {c.model}/{c.strategy} schema={schema_name(c) or '-'} max={c.max_tokens}")
        return 0
    session = open_session()
    if not preflight(session):
        return 1
    tap, rows = Tap(), []
    for i, case in enumerate(cases, 1):
        if tap.calls >= MAX_CALLS:
            print(f"호출 상한 {MAX_CALLS} 에 닿아 멈춘다.")
            break
        rows.append(await run_case(session, tap, case))
        print_row(i, rows[-1])
        await asyncio.sleep(PAUSE_S)
    summary(rows, tap, session)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
