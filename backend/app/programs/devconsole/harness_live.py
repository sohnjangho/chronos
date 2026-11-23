"""개발 콘솔 하네스: 11-23 에 더한 코드 강제 규칙과 그 실엔진 차단 시험(live_harness).

규칙마다 진짜 함수(도구·루프·생성·사진 판독·기한 계산)를 대본 입력으로 임시 DB(harness_db)에서 돌리고 관측값을 돌려준다.
네트워크·LLM 을 쓰지 않는다: 정보 API 는 generic.HARNESS_TRANSPORT(이 작업 맥락에만 보이는 가짜 서버, IP 꼴 주소라 이름
풀이도 없다), LLM 은 대본 transport 이거나 연결이 없다(부르기 전에 멈춘다). 운영 DB 에는 쓰지 않는다.
세션 기록 수(session_counts)는 기록된 단계·현장 항목에서만 센다. 기록이 없는 규칙은 None(지어내지 않는다).
"""

import asyncio
import inspect
import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent import loop
from app.agent.context import UiContext
from app.agent.generation import REPEAT_REASON, generate
from app.core.model import Activity, CalendarSpec, Schedule, WbsNode
from app.domains.loader import load
from app.errors import ApiError
from app.harness.conditions import Condition
from app.info import generic
from app.llm.client import LlmClient
from app.programs.devconsole.harness_db import (
    HARNESS_CHAT_ID,
    ScriptedLiner,
    add_llm_connection,
    run_isolated_turn,
    temp_session,
)
from app.programs.progress import field
from app.programs.schedule.router import router as schedule_router
from app.security.crypto import encrypt
from app.security.deps import require_editor
from app.store import evidence_reuse
from app.store.evidence import INFO_MODE
from app.store.messages import FIELD_READ_ONLY_MESSAGE
from app.store.schedules import create_schedule
from app.store.tables import (
    ChatSession,
    EvidenceItem,
    EvidenceLink,
    EvidenceSearch,
    FieldItem,
    InfoConnection,
    ScheduleDraft,
    User,
    WorkflowStep,
)
from app.tools import registry
from app.tools.context import ToolContext
from app.tools.data import info_call
from app.tools.generate import extract_conditions
from app.tools.registry import ToolResult

Run = tuple[str, dict[str, Any], bool]  # (시뮬레이션 입력, 관측값, 하네스가 실제로 막았는가)

RULES: list[dict[str, Any]] = [
    {
        "id": "H-INFO-01", "group": "바깥 정보", "area": "정보 API",
        "title": "정보 API 경로가 연결 주소 밖으로 나가면 부르지 않음",
        "description": "path 는 / 로 시작하는 상대 경로만 받고(//·..·@·\\·://·%2e 꼴 거절), 만든 주소의 scheme·host·port·경로 "
                       "앞부분이 연결 주소와 같은지 다시 맞춘다. 거절은 부르기 전이라 요청 수(4번 한도)에 들지 않는다.",
        "code": "app/info/generic.py:request_problem·_target · app/tools/data/info_call.py",
        "mode": "도구 결과로 거절(부르기 전)",
        "feedback_sample": '{"error": "path 에 「..」는 쓸 수 없습니다 — 연결 주소 밖으로 나가는 경로는 부르지 않습니다."}',
    },
    {
        "id": "H-INFO-02", "group": "바깥 정보", "area": "정보 API",
        "title": "응답에 키가 되돌아와도 도구 결과·근거에 키를 남기지 않음",
        "description": "응답 본문·Content-Type·주소에서 키(그대로·%XX·&#..;·\\u00XX 꼴, key_name 질의 값)를 지우고, 지운 뒤에도 "
                       "풀어 보아 남으면 본문을 통째로 버린다. 300KB·15초 안에서만 읽는다.",
        "code": "app/info/generic.py:scrub·_clean·key_survives",
        "mode": "구조로 강제 — 키 지우기",
        "feedback_sample": '{"body": "{\\"echo\\": \\"serviceKey=[키지움]\\"}"}',
    },
    {
        "id": "H-INFO-03", "group": "바깥 정보", "area": "정보 API",
        "title": "정보 API 조회는 한 요청에 4번까지(실패 포함)",
        "description": "그 대화의 마지막 사용자 메시지 뒤에 한 info.call 을 세어 4번이 넘으면 부르지 않고 받은 값·분야 기본값을 "
                       "쓰라고 돌려준다. 날씨 조회·근거 검색과 따로 센다.",
        "code": "app/tools/data/info_call.py:LIMIT",
        "mode": "도구 결과로 거절",
        "feedback_sample": '{"error": "이번 요청에서 정보 API 조회를 4번 했습니다. 받은 값이나 분야 기본값을 쓰세요."}',
    },
    {
        "id": "H-EVR-01", "group": "바깥 정보", "area": "근거 검색",
        "title": "저장된 근거는 붙은 것·30일 안·「다시 쓰지 않기」 아님·낱말이 모두 맞을 때만 다시 씀",
        "description": "evidence.search 가 Liner 를 부르기 전에 저장된 근거를 찾되, 일정에 붙지 않았거나 30일이 지났거나 "
                       "다시 쓰지 않기로 한 근거는 쓰지 않는다. fresh=true 면 저장된 근거를 보지 않고 새로 찾는다.",
        "code": "app/store/evidence_reuse.py:find · app/tools/data/search_evidence.py",
        "mode": "코드가 고름(에이전트는 맞는지만 판단)",
        "feedback_sample": '{"reused": true, "hint": "저장된 근거입니다. 질문에 맞지 않으면 fresh 를 true 로 다시 부르세요."}',
    },
    {
        "id": "H-ROLE-01", "group": "권한", "area": "역할",
        "title": "현장 관리자는 일정 고치기·승인·상신 도구와 경로를 못 씀(사용자는 그대로)",
        "description": "REST 는 require_editor(403 field_read_only), 도구는 ToolContext.require_editor 로 같은 글을 돌려준다. "
                       "현장 회신·지연 기록과 읽기는 연다.",
        "code": "app/security/deps.py:require_editor · app/tools/context.py:require_editor",
        "mode": "403 · 도구 결과로 거절",
        "feedback_sample": '{"error": "현장 관리자는 일정을 고치거나 승인·거부할 수 없습니다."}',
    },
    {
        "id": "H-IMP-01", "group": "가져오기·생성", "area": "루프",
        "title": "가져오기 단추 글만 confirmed 를 채우고, 한 턴의 같은 확인·가져오기 되풀이는 거절",
        "description": "[일정 초안으로 가져오기]가 보낸 정해진 글이면 그 파일의 schedule.import 에 confirmed=true 를 넣는다. "
                       "다른 글은 넣지 않는다. 같은 턴에 같은 파일을 다시 확인·가져오면 실행하지 않고 까닭을 돌려준다.",
        "code": "app/agent/loop.py:IMPORT_BUTTON·_button_import·_import_again",
        "mode": "루프가 인자를 채움 · 도구 결과로 거절",
        "feedback_sample": '{"error": "이번 턴에 이 파일(#7)은 이미 가져왔습니다. 다시 부르지 말고 받은 결과를 사용자에게 알리세요."}',
    },
    {
        "id": "H-GEN-01", "group": "가져오기·생성", "area": "생성",
        "title": "같은 위반이 두 회차 이어지면 고치기를 멈추고 가장 나은 초안을 남김",
        "description": "바로 앞 회차와 위반(조건·액티비티·양·글)이 똑같으면 다음 고침을 부르지 않고, 그때까지 가장 나은 초안과 "
                       "부딪히는 조건을 돌려준다.",
        "code": "app/agent/generation.py:_Loop.same_as_before",
        "mode": "코드가 멈춤",
        "feedback_sample": '{"ok": false, "reason": "같은 위반이 두 회차 이어져 고치기를 멈췄습니다. 조건을 모두 맞추지 못했습니다."}',
    },
    {
        "id": "H-FLD-01", "group": "현장", "area": "사진 판독",
        "title": "사진 판독은 그림 읽기 모델의 답이 없으면 진도 %를 만들지 않음",
        "description": "사진이 없거나 그림 읽기 모델을 부를 수 없거나 답을 읽지 못하면 「판독하지 않음」과 까닭만 남기고 진도 값은 "
                       "비운다(승인함 상신도 막힌다).",
        "code": "app/programs/progress/field.py:upload_photo·_read_photo",
        "mode": "구조로 강제 — 숫자 비움",
        "feedback_sample": '{"response_choice": "unread", "reported_progress": null, "unread_reason": "사진이 없어 판독하지 않았습니다."}',
    },
    {
        "id": "H-DATE-01", "group": "일정 계산", "area": "조건 뽑기",
        "title": "「착수 후 N주」 기한은 코드가 시작일로 날짜를 셈함",
        "description": "LLM 은 기간(amount·unit)만 내고, 날짜는 코드가 시작일 + 기간 − 1일(주 = 7일, 개월 = 같은 날짜)로 셈해 "
                       "finish_by 조건으로 만든다. 시작일을 모르면 조건을 만들지 않고 묻는다.",
        "code": "app/tools/generate/extract_conditions.py:_after·conditions_from",
        "mode": "코드가 계산",
        "feedback_sample": '{"id": "in.finish_by", "params": {"date": "2027-09-26"}, "text": "착수 후 16주 안에 완료 (시작일 2027-06-07 + 16주)"}',
    },
]


# ── 바깥 정보: 정보 API ──────────────────────────────────────────────

HARNESS_KEY = "HARNESSkey+7a/Zq9=="  # 가짜 디코딩 키(+ / = 섞음)
INFO_BASE = "https://93.184.216.34/B090041/openapi/service/SpcdeInfoService"  # 공인 IP 꼴 — 이름 풀이를 하지 않는다
INFO_PATH = "/getRestDeInfo"
BAD_PATHS = ("//evil.example/x", "/../../admin", "/%2e%2e/admin", "/x@evil.example/", "/a\\..\\b", "http://evil.example/x")
EXPECTED_INFO_LIMIT = 4  # 규칙 글의 「4번」


def _holidays() -> dict:
    return {"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                         "body": {"items": {"item": [{"dateName": "기독탄신일", "locdate": 20271225}]}, "totalCount": 1}}}


async def _chunks(body: bytes):
    yield body


class _FakeApi:
    """가짜 공공데이터 서버. 받은 요청을 남기고 늘 body(JSON)를 아직 읽지 않은 흐름으로 준다(실제 소켓처럼)."""

    def __init__(self, body: dict) -> None:
        self.body, self.requests = body, []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        raw = json.dumps(self.body, ensure_ascii=False).encode()
        return httpx.Response(200, headers={"content-type": "application/json;charset=UTF-8"}, content=_chunks(raw))


async def _with_api(api: _FakeApi, work: Callable[[], Any]) -> Any:
    token = generic.HARNESS_TRANSPORT.set(httpx.MockTransport(api.handle))
    try:
        return await work()
    finally:
        generic.HARNESS_TRANSPORT.reset(token)


class _InfoBench:
    """임시 DB 의 범용 정보 API 연결 하나와 대화 하나. call 은 가짜 서버로 info.call 을 부른다."""

    def __init__(self, s: Session, user: User, api: _FakeApi) -> None:
        conn = InfoConnection(name="하네스 공휴일 API", preset="generic", base_url=INFO_BASE,
                              secret_ciphertext=encrypt(HARNESS_KEY), secret_last4=HARNESS_KEY[-4:], status="ok",
                              key_in="query", key_name="serviceKey")
        chat = ChatSession(user_id=user.id, title="")
        s.add_all([conn, chat])
        s.commit()
        self.s, self.api, self.conn_id = s, api, conn.id
        self.ctx = ToolContext(session=s, user=user, schedule_id=None, emit=lambda _e: None, chat_session_id=chat.id)

    def call(self, path: str = INFO_PATH) -> ToolResult:
        args = {"connection_id": self.conn_id, "path": path, "params": {"solYear": "2027"}}
        return asyncio.run(_with_api(self.api, lambda: registry.call("info.call", args, self.ctx)))


def _info_path(_cfg: dict) -> Run:
    api = _FakeApi(_holidays())
    with temp_session() as (s, user):
        bench = _InfoBench(s, user, api)
        refused = [{"path": p, "ok": (r := bench.call(p)).ok, "error": r.error} for p in BAD_PATHS]
        sent = len(api.requests)
        control = bench.call()
        counted = s.scalar(select(func.count()).select_from(EvidenceSearch).where(EvidenceSearch.mode == INFO_MODE))
    fb = {"ok": not any(r["ok"] for r in refused), "rule_id": "H-INFO-01", "connection": INFO_BASE, "refused": refused,
          "requests_for_refused": sent, "control": {"path": INFO_PATH, "ok": control.ok, "error": control.error},
          "counted": counted}
    held = fb["ok"] and sent == 0 and control.ok
    return f"연결 주소 밖으로 나가는 path {len(BAD_PATHS)}가지 + 바른 path 하나 → info.call 실실행(가짜 서버)", fb, held


def _info_key(_cfg: dict) -> Run:
    encoded = quote(HARNESS_KEY, safe="")
    body = _holidays()
    body["response"]["header"]["resultMsg"] = f"echo serviceKey={HARNESS_KEY}"
    body["response"]["body"] |= {"raw": HARNESS_KEY, "encoded": encoded,
                                 "url": f"{INFO_BASE}{INFO_PATH}?serviceKey={encoded}&solYear=2027"}
    api = _FakeApi(body)
    with temp_session() as (s, user):
        result = _InfoBench(s, user, api).call()
        text = json.dumps(result.output if result.ok else {"error": result.error}, ensure_ascii=False)
        saved = " ".join([*(f"{i.title} {i.url} {i.description}" for i in s.scalars(select(EvidenceItem))),
                          *s.scalars(select(EvidenceSearch.query))])
    fb = {"ok": result.ok, "rule_id": "H-INFO-02", "planted_forms": 4,
          "key_sent_to_server": any(generic.key_survives(str(r.url), HARNESS_KEY) for r in api.requests),
          "key_in_tool_result": generic.key_survives(text, HARNESS_KEY),
          "key_in_saved_evidence": generic.key_survives(saved, HARNESS_KEY),
          "masked": text.count(generic.MASK), "tool_result_body": (result.output or {}).get("body", "")[:400]}
    held = (result.ok and fb["key_sent_to_server"] and not fb["key_in_tool_result"]
            and not fb["key_in_saved_evidence"] and fb["masked"] >= 1)
    return "가짜 서버가 응답에 키를 네 꼴(그대로·인코딩·주소 안·머리 글)로 되돌림 → info.call 실실행", fb, held


def _info_limit(_cfg: dict) -> Run:
    api = _FakeApi(_holidays())
    with temp_session() as (s, user):
        bench = _InfoBench(s, user, api)
        got = [bench.call() for _ in range(EXPECTED_INFO_LIMIT + 1)]
    fb = {"ok": not got[-1].ok, "rule_id": "H-INFO-03", "limit": info_call.LIMIT,
          "results": ["ok" if r.ok else "refused" for r in got], "requests": len(api.requests),
          "fifth_error": got[-1].error}
    held = (fb["results"] == ["ok"] * EXPECTED_INFO_LIMIT + ["refused"] and fb["requests"] == EXPECTED_INFO_LIMIT
            and got[-1].error == info_call.LIMIT_MESSAGE)
    return f"한 요청에서 info.call 을 {EXPECTED_INFO_LIMIT + 1}번 부름 → 실실행(가짜 서버)", fb, held


# ── 바깥 정보: 근거 다시 쓰기 ─────────────────────────────────────────

REUSE_QUERY = "철근콘크리트 층당 골조 공기"
REUSABLE = "붙음·1일·살아 있음"
REUSE_CASES = ((REUSABLE, True, 1, False), ("붙은 곳 없음", False, 1, False), ("31일 지남", True, 31, False),
               ("다시 쓰지 않기", True, 1, True))  # (이름, 붙음, 지난 날, 다시 쓰지 않기)


def _seed_evidence(s: Session, now: datetime) -> dict[int, str]:
    search = EvidenceSearch(query=REUSE_QUERY, mode="web", ok=True, result_count=len(REUSE_CASES))
    s.add(search)
    s.flush()
    names: dict[int, str] = {}
    for n, (name, linked, days, retired) in enumerate(REUSE_CASES):
        item = EvidenceItem(search_id=search.id, title=f"{name} — 철근콘크리트 골조 층당 공기 기준",
                            url=f"https://example.org/evidence/{n}", hostname="example.org",
                            description="층당 골조 공기 7일", created_at=(now - timedelta(days=days)).replace(tzinfo=None),
                            retired=retired)
        s.add(item)
        s.flush()
        names[item.id] = name
        if linked:
            s.add(EvidenceLink(evidence_id=item.id, schedule_id=1))
    s.commit()
    return names


def _evidence_reuse(_cfg: dict) -> Run:
    now = datetime.now(UTC)
    with temp_session() as (s, user):
        names = _seed_evidence(s, now)
        chat = ChatSession(user_id=user.id, title="")
        s.add(chat)
        s.commit()
        found = [names[f.item.id] for f in evidence_reuse.find(s, REUSE_QUERY, 5, now=now)]
        ctx = ToolContext(session=s, user=user, schedule_id=None, emit=lambda _e: None, chat_session_id=chat.id)
        reused = asyncio.run(registry.call("evidence.search", {"query": REUSE_QUERY}, ctx))
        s.commit()  # 다시 쓴 줄을 닫아야 새로 찾기의 실패 줄(따로 연 세션)이 쓰기 잠금을 기다리지 않는다
        fresh = asyncio.run(registry.call("evidence.search", {"query": REUSE_QUERY, "fresh": True}, ctx))
        tried = s.scalar(select(func.count()).select_from(EvidenceSearch).where(
            EvidenceSearch.chat_session_id == chat.id, EvidenceSearch.mode == "web"))
    out = reused.output or {}
    fb = {"ok": bool(out.get("reused")), "rule_id": "H-EVR-01", "query": REUSE_QUERY, "found": found,
          "not_found": [n for n in names.values() if n not in found], "tool_reused": out.get("reused") is True,
          "tool_results": [names.get(r["evidence_id"]) for r in out.get("results", [])],
          "fresh_reused": bool((fresh.output or {}).get("reused")), "fresh_tried_liner": tried == 1,
          "fresh_error": fresh.error}
    held = (found == [REUSABLE] and fb["tool_reused"] and fb["tool_results"] == [REUSABLE] and not fb["fresh_reused"]
            and fb["fresh_tried_liner"])
    return "저장된 근거 넷(붙음·안 붙음·31일·다시 쓰지 않기) → evidence_reuse.find·evidence.search(fresh) 실실행", fb, held


# ── 권한 ────────────────────────────────────────────────────────────

ROLE_TOOL = "schedule.create_project"
EDIT_ROUTE = ("PATCH", "/api/schedules/{schedule_id}")


def editor_tools() -> set[str]:
    """현장 관리자에게 막힌 도구: 도구 함수가 ctx.require_editor() 를 부르는 것(서버가 막는 바로 그 줄을 읽는다)."""
    registry.load_all()
    found = set()
    for spec in registry.list_tools(enabled_only=False):
        fn = registry._functions.get(spec.name)
        if fn is not None and "ctx.require_editor()" in inspect.getsource(fn):
            found.add(spec.name)
    return found


def _calls(dep: Any) -> list[Callable]:
    return [d.call for d in dep.dependencies] + [c for d in dep.dependencies for c in _calls(d)]


def _route_guarded() -> bool:
    method, path = EDIT_ROUTE
    route = next(r for r in schedule_router.routes if getattr(r, "path", "") == path and method in getattr(r, "methods", ()))
    return require_editor in _calls(route.dependant)


def _route_answer(user: User) -> dict | str:
    try:
        require_editor(user)
    except ApiError as e:
        return {"status": e.status_code, "code": e.code}
    return "통과"


def _role(_cfg: dict) -> Run:
    with temp_session() as (s, _admin):
        field_user = User(login_id="harness-field", name="현장 시험", role="field", password_hash="-")
        plain_user = User(login_id="harness-user", name="사용자 시험", role="user", password_hash="-")
        s.add_all([field_user, plain_user])
        s.commit()

        def run(u: User) -> ToolResult:
            ctx = ToolContext(session=s, user=u, schedule_id=None, emit=lambda _e: None)
            return asyncio.run(registry.call(ROLE_TOOL, {"name": "하네스 새 현장"}, ctx))

        by_field, by_user = run(field_user), run(plain_user)
        fb = {"ok": not by_field.ok, "rule_id": "H-ROLE-01", "tool": ROLE_TOOL,
              "field_tool": {"ok": by_field.ok, "error": by_field.error},
              "user_tool": {"ok": by_user.ok, "error": by_user.error},
              "route": " ".join(EDIT_ROUTE), "route_has_guard": _route_guarded(),
              "field_route": _route_answer(field_user), "user_route": _route_answer(plain_user)}
    held = (not by_field.ok and by_field.error == FIELD_READ_ONLY_MESSAGE and by_user.ok and fb["route_has_guard"]
            and fb["field_route"] == {"status": 403, "code": "field_read_only"} and fb["user_route"] == "통과")
    return f"현장 관리자·사용자가 `{ROLE_TOOL}` 도구와 {' '.join(EDIT_ROUTE)} 경로 지킴이를 부름 → 실실행", fb, held


# ── 가져오기·생성 ───────────────────────────────────────────────────

IMPORT_FILE = 7
BUTTON_TEXT = f"네, 확인했으니 이 파일(#{IMPORT_FILE})을 일정 초안으로 가져와 줘."
OTHER_TEXT = f"이 파일(#{IMPORT_FILE})을 일정 초안으로 가져와 줘"


def _confirmed(seen: dict) -> bool:
    inputs = [json.loads(i) for i in seen["step_inputs"]]
    return bool(inputs) and inputs[0].get("confirmed") is True


def _repeat_answers() -> tuple[str | None, str | None]:
    """루프의 기록(note_import)과 거절(_import_again)을 대본 결과로: 확인 뒤 같은 확인, 가져온 뒤 같은 가져오기."""
    turn = loop._Turn(None, None, HARNESS_CHAT_ID, UiContext(), None)  # type: ignore[arg-type]
    check = loop._Call("c1", "schedule.import", {"file_id": IMPORT_FILE}, json.dumps({"file_id": IMPORT_FILE}))
    turn.note_import(check, ToolResult(ok=True, output={"step": "checked"}, error=None, ms=1))
    second_check = turn._import_again(check)
    args = {"file_id": IMPORT_FILE, "confirmed": True, "domain": "construction", "level": "L3"}
    imported = loop._Call("c2", "schedule.import", args, json.dumps(args))
    turn.note_import(imported, ToolResult(ok=True, output={"step": "imported", "draft": {"draft_id": 1}}, error=None, ms=1))
    return second_check, turn._import_again(imported)


def _import(cfg: dict) -> Run:
    args = json.dumps({"file_id": IMPORT_FILE})
    button = run_isolated_turn(cfg, ScriptedLiner(1, tool="schedule.import", arguments=args), BUTTON_TEXT)
    other = run_isolated_turn(cfg, ScriptedLiner(1, tool="schedule.import", arguments=args), OTHER_TEXT)
    second_check, second_import = _repeat_answers()
    fb = {"rule_id": "H-IMP-01", "button_text": BUTTON_TEXT, "button_turn_confirmed": _confirmed(button),
          "button_step_input": button["step_inputs"][:1], "other_text": OTHER_TEXT,
          "other_text_confirmed": _confirmed(other), "other_step_input": other["step_inputs"][:1],
          "second_check": second_check, "second_import": second_import}
    held = (fb["button_turn_confirmed"] and not fb["other_text_confirmed"]
            and second_check == loop.CHECK_AGAIN.format(IMPORT_FILE)
            and second_import == loop.IMPORT_AGAIN.format(IMPORT_FILE))
    return ("대본 LLM 이 confirmed 없이 schedule.import 를 부름(단추 글 턴 · 다른 글 턴) → 임시 DB 에서 loop.run_turn 실실행, "
            "같은 턴 되풀이는 루프의 note_import·_import_again 실실행"), fb, held


def _act(i: str, name: str, wbs: str, od: int, preds: tuple[str, ...] = (), kind: str = "task") -> dict:
    return {"id": i, "name": name, "kind": kind, "wbs": wbs, "od": od, "tags": [],
            "predecessors": [{"pred": p, "type": "FS", "lag": 0} for p in preds]}


GEN_WBS = {"wbs": [{"code": "1", "name": "사무동", "parent": None}, {"code": "1.1", "name": "기초", "parent": "1"},
                   {"code": "1.1.1", "name": "기초 공사", "parent": "1.1"}, {"code": "1.2", "name": "골조", "parent": "1"},
                   {"code": "1.2.1", "name": "지상 골조", "parent": "1.2"}]}
GEN_FINISH = "2027-04-05"  # 1층 골조 20일이면 맞는 준공(주 6일·2027 공휴일, 착공 2027-03-01)


def _draft(frame_od: int) -> str:
    acts = [_act("A1000", "착공", "1.1.1", 0, kind="start_ms"), _act("A1010", "기초 철근 배근", "1.1.1", 10, ("A1000",)),
            _act("A1020", "1층 골조", "1.2.1", frame_od, ("A1010",)),
            _act("A1030", "준공", "1.2.1", 0, ("A1020",), kind="finish_ms")]
    return json.dumps({"activities": acts}, ensure_ascii=False)


def _repair(_cfg: dict) -> Run:
    script = ScriptedLiner(replies=[json.dumps(GEN_WBS, ensure_ascii=False), _draft(23), _draft(23), _draft(20)])
    finish_by = Condition("in.finish_by", "input", "finish_by", {"date": GEN_FINISH}, f"준공 {GEN_FINISH}까지", "프롬프트")
    with temp_session() as (s, user):
        add_llm_connection(s)
        s.commit()
        ctx = ToolContext(session=s, user=user, schedule_id=None, emit=lambda _e: None)
        llm = LlmClient(s, transport=httpx.MockTransport(script.handle))
        r = asyncio.run(generate(ctx, llm, domain="construction", level="L3", request="5층 사무동 신축 일정",
                                 facts=[{"label": "착공일", "value": "2027-03-01", "source": "프롬프트"}],
                                 inputs=[finish_by], max_rounds=5))
        saved = r.draft_id is not None and s.get(ScheduleDraft, r.draft_id) is not None
    fb = {"ok": r.ok, "rule_id": "H-GEN-01", "rounds": [x.violations for x in r.rounds], "llm_requests": len(script.bodies),
          "reason": r.reason, "draft_saved": saved, "conflict": r.conflict}
    held = fb["rounds"] == [1, 1] and fb["llm_requests"] == 3 and r.reason == REPEAT_REASON and saved
    return "대본 LLM 이 같은 3일 늦은 초안을 두 번 냄(세 번째는 맞는 초안) → 임시 DB 에서 generation.generate 실실행", fb, held


# ── 현장 · 일정 계산 ─────────────────────────────────────────────────

PHOTO = "data:image/png;base64,iVBORw0KGgo="  # 그림 머리만 있는 가짜 사진


def _photo(_cfg: dict) -> Run:
    plan = Schedule(start=date(2027, 3, 1), calendar=CalendarSpec(days_per_week=5), wbs=(WbsNode("1", "골조", None),),
                    activities=(Activity("A", "1층 골조", "task", "1", 5),), relations=())
    cases = []
    with temp_session() as (s, _user):  # LLM 연결이 없다 — 그림 읽기 모델을 부를 수 없다
        sid = create_schedule(s, name="하네스 현장", domain="construction", level="L3", schedule=plan, conditions=[],
                              by_kind="agent", by_name="하네스", note="하네스 시험")
        for label, data_url in (("사진 없음", None), ("그림 읽기 모델 연결 없음", PHOTO)):
            body = field.PhotoUploadIn(activity_id="A", photo_name="골조.jpg", photo_data_url=data_url)
            asyncio.run(field.upload_photo(s, sid, body))
            item = s.scalars(select(FieldItem).where(FieldItem.kind == "photo").order_by(FieldItem.id.desc())).first()
            cases.append({"case": label, "reported_progress": item.reported_progress,
                          "ai_progress": item.payload_json.get("ai_progress"), "response_choice": item.response_choice,
                          "why": item.payload_json.get("unread_reason")})
    fb = {"rule_id": "H-FLD-01", "cases": cases}
    held = all(c["reported_progress"] is None and c["ai_progress"] is None and c["response_choice"] == field.UNREAD
               for c in cases)
    return "사진 없이 · 그림 읽기 연결 없이 현장 사진을 올림 → 임시 DB 에서 field.upload_photo 실실행", fb, held


def _deadline(_cfg: dict) -> Run:
    args = extract_conditions.ExtractIn(text="2027년 6월 7일 착수, 착수 후 16주 안에 완료", domain="construction", level="L3")
    proposed = [
        extract_conditions._Proposed(kind="start_after", text="2027년 6월 7일 착수", date="2027-06-07"),
        extract_conditions._Proposed(kind="finish_by", text="착수 후 16주 안에 완료", after_start={"amount": 16, "unit": "주"}),
    ]
    kept, dropped, unknown = extract_conditions.conditions_from(proposed, load("construction"), args, [])
    finish = next((c for c in kept if c["kind"] == "finish_by"), None)
    fb = {"ok": True, "rule_id": "H-DATE-01", "start": "2027-06-07", "after_start": "16주",
          "finish_by": finish["params"]["date"] if finish else None, "text": finish["text"] if finish else None,
          "dropped": [d.model_dump() for d in dropped], "unknown": unknown}
    return "LLM 답 대신 대본 조건(착수 2027-06-07 · 착수 후 16주) → extract_conditions.conditions_from 실실행", fb, \
        fb["finish_by"] == "2027-09-26"


RUNNERS: dict[str, Callable[[dict], Run]] = {
    "H-INFO-01": _info_path, "H-INFO-02": _info_key, "H-INFO-03": _info_limit, "H-EVR-01": _evidence_reuse,
    "H-ROLE-01": _role, "H-IMP-01": _import, "H-GEN-01": _repair, "H-FLD-01": _photo, "H-DATE-01": _deadline,
}


def run(rule_id: str, cfg: dict[str, Any]) -> Run:
    registry.load_all()
    return RUNNERS[rule_id](cfg)


# ── 세션 기록 ───────────────────────────────────────────────────────


def _error(step: WorkflowStep) -> str:
    if step.status != "failed":
        return ""
    try:
        return str(json.loads(step.output_json or "")["error"])
    except (ValueError, KeyError, TypeError):
        return ""


def session_counts(session: Session, steps: list[WorkflowStep],
                   signals: Callable[[WorkflowStep], list[str]]) -> dict[str, dict[str, int | None]]:
    """규칙마다 {passed, blocked}: 기록된 단계(steps)와 현장 사진 항목에서만 센다. 기록이 없으면 None."""
    info = [s for s in steps if s.tool == "info.call"]
    info_done = sum(s.status == "done" for s in info)
    bad_path = (generic.BAD_PART.split("{")[0], generic.BAD_START)
    editors = editor_tools()
    stopped = sum("repair_stopped" in signals(s) for s in steps)
    generated = sum(s.tool == "generate.run" and s.status == "done" and "repair_stopped" not in signals(s) for s in steps)
    photos = list(session.scalars(select(FieldItem).where(FieldItem.kind == "photo")))
    return {
        "H-INFO-01": {"passed": info_done, "blocked": sum(_error(s).startswith(bad_path) for s in info)},
        "H-INFO-02": {"passed": info_done, "blocked": sum(generic.KEY_IN_BODY in (s.output_json or "") for s in info)},
        "H-INFO-03": {"passed": info_done, "blocked": sum(_error(s) == info_call.LIMIT_MESSAGE for s in info)},
        "H-EVR-01": {"passed": None, "blocked": None},
        "H-ROLE-01": {"passed": sum(s.tool in editors and s.status == "done" for s in steps),
                      "blocked": sum(_error(s) == FIELD_READ_ONLY_MESSAGE for s in steps)},
        "H-IMP-01": {"passed": sum(s.tool == "schedule.import" and s.status == "done" for s in steps),
                     "blocked": sum("import_refused" in signals(s) for s in steps)},
        "H-GEN-01": {"passed": generated, "blocked": stopped},
        "H-FLD-01": {"passed": sum(p.reported_progress is not None for p in photos),
                     "blocked": sum(p.response_choice == field.UNREAD for p in photos)},
        "H-DATE-01": {"passed": None, "blocked": None},
    }
