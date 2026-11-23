"""한국AI통신 REST 연결 진단(계획 4 Task 59, 0단계 P1~P4). 설정 화면의 「연결 진단」과 실측 스크립트가 같이 쓴다.

- 단계 함수는 이미 만든 연결 값(`DiagnosticConn`)과 주입한 `httpx.AsyncClient` 를 받아 `DiagnosticStep` 을 돌려준다.
  찍지 않고, 환경 변수를 읽지 않고, 끝내지 않는다. 예외도 던지지 않는다(실패는 `ok=False`, 예외는 종류만).
- `detail`·`notes` 는 이미 지운 글이다: 키·Account ID·번호(원문·하이픈 꼴·+82 꼴)·8자리 넘는 숫자 묶음·40자 넘는 토큰.
  응답은 칸 이름(구조)만 남기고, 발신번호는 숫자 없이 순번·상태만 남긴다.
- 실제 문자는 `check_send_sms(..., send_test_sms=True)` 일 때만 보낸다. 기본 「연결 테스트」는 보내지 않는다.
- 요청 상한 8번(`Calls`; P1 1 + P2 1 + P3 4 + P4 1 = 7). 리다이렉트는 요청마다 따르지 않는다. DB 에 쓰지 않는다.
- 한국 밖 IP 에서 문자를 보내면 403 `overseas_ip_blocked` 가 온다고 문서에 있다.

본 문서(2026-11-23, https://docs.koreaaitel.com):
- api-reference — 인증 `Authorization: Bearer <API Key>`, 기본 주소 https://api.koreaaitel.com
- api-reference/claw-ops-api/sender-numbers/list-sender-numbers — `GET /v1/accounts/{accountId}/sender-numbers`
  → `{senderNumbers: [{number, status: approved|pending}]}`
- api-reference/claw-ops-api/messages/send-message — `POST …/messages` 본문 `To`·`From`·`Body`·`Type`(sms|lms|mms|ata|bms)·
  `IdempotencyKey`(같은 키로 다시 보내면 보내지 않고 1회차 결과) → 201, 칸 `messageId`·`status`·`failureCode`…
  오류 본문 `{error, code}`(400·401·403·422·429, 429 는 `Retry-After`)
- api-reference/claw-ops-api/messages/get-message — `GET …/messages/{messageId}`, `status` queued|sent|failed|received,
  `failureCode`(실패 사유 코드 — 분기는 이것으로)
- messages(안내) — `GET …/messages?status=received&pageSize=20` → `{data: [...], meta: {page, pageSize, total}}`
"""

import asyncio
import re
import time
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx

DEFAULT_BASE_URL = "https://api.koreaaitel.com"
MAX_REQUESTS = 8
POLL_TIMES = 4
POLL_GAP_S = 5
SMS_TEXT = "[ChronOS] 실측 문자입니다."
FINAL = ("sent", "failed")
LABELS = {"P1": "인증 + 발신번호 목록", "P2": "시험 문자 1건 보내기", "P3": "보낸 문자 상태 조회", "P4": "받은 문자 목록"}
_SEP = r"[\s.\-()]*"
_PHONE_RE = re.compile(r"(?:\+?82[\s.\-]?|0)\d{1,2}[\s.\-]?\d{3,4}[\s.\-]?\d{4}")  # 010-0000-0000 · +82 10-…
_DIGITS_RE = re.compile(r"\d{8,}")  # 7자리 넘는 숫자 묶음
_TOKEN_RE = re.compile(r"[A-Za-z0-9%+/=_\-]{40,}")

Sleep = Callable[[float], Awaitable[None]]


@dataclass(frozen=True)
class DiagnosticConn:
    """진단에 쓸 연결 값. 키·번호는 이 값과 요청에만 있고 결과에는 없다."""

    base_url: str
    key: str
    account_id: str
    sender: str = ""  # 발신번호(P1 에서 승인 여부를 봄, P2 의 From)
    test_to: str = ""  # 시험 문자를 받을 번호(P2 의 To)


@dataclass
class DiagnosticStep:
    id: str  # "P1" … "P4"
    label: str
    ok: bool
    detail: str  # 한 줄. 실패면 짧은 코드로 시작(unauthorized · http_401 · still_queued · ConnectError …)
    latency_ms: int | None = None  # 이 단계 요청 시간의 합(기다린 시간 빼고)
    skipped: bool = False  # 돌리지 않음(ok 는 False, detail 에 까닭)
    notes: list[str] = field(default_factory=list)  # 접어 보일 기계 출력(구조·조회마다 상태·오류 글)


class Calls:
    """한 번의 진단에서 보낸 요청 수. 상한에 닿으면 더 보내지 않는다."""

    def __init__(self, limit: int = MAX_REQUESTS) -> None:
        self.limit = limit
        self.sent = 0


class _Fail(Exception):
    pass


def _digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _number_patterns(number: str) -> list[re.Pattern[str]]:
    """번호 하나를 국내 꼴·+82 꼴로, 사이에 하이픈·빈칸이 있어도 찾는 정규식들."""
    d = _digits(number)
    if not d:
        return []
    forms = {d}
    if d.startswith("82"):
        forms.add("0" + d[2:])
    elif d.startswith("0"):
        forms.add("82" + d[1:])
    return [re.compile(r"\+?" + _SEP.join(f)) for f in forms]


def scrub(text: object, *, secrets: list[str], numbers: list[str], limit: int = 200) -> str:
    """키·Account ID·번호·긴 숫자 묶음·긴 토큰을 지우고 한 줄로 자른다."""
    out = str(text)
    for s in sorted({s for s in secrets if s}, key=len, reverse=True):
        out = out.replace(s, "…")
    for rx in (rx for n in numbers if n for rx in _number_patterns(n)):
        out = rx.sub("…", out)
    for rx in (_PHONE_RE, _DIGITS_RE, _TOKEN_RE):
        out = rx.sub("…", out)
    return re.sub(r"\s+", " ", out).strip()[:limit]


def structure(obj: object, depth: int = 0) -> str:
    """dict/list 의 칸 이름만 펼쳐 한 줄로 보인다(값은 빼고)."""
    if depth > 5:
        return "…"
    if isinstance(obj, dict):
        return "{" + ", ".join(f"{k}: {structure(v, depth + 1)}" for k, v in obj.items()) + "}"
    if isinstance(obj, list):
        return f"[{len(obj)}× {structure(obj[0], depth + 1)}]" if obj else "[]"
    return type(obj).__name__


class _Run:
    """단계 하나의 요청·기록. 글은 모두 지워서 남긴다."""

    def __init__(self, conn: DiagnosticConn, http: httpx.AsyncClient, calls: Calls | None) -> None:
        self.conn, self.http = conn, http
        self.calls = calls if calls is not None else Calls()
        self.base = f"{conn.base_url.rstrip('/')}/v1/accounts/{conn.account_id}"
        self.ms = 0
        self.notes: list[str] = []

    def clean(self, text: object, limit: int = 200) -> str:
        return scrub(text, secrets=[self.conn.key, self.conn.account_id],
                     numbers=[self.conn.sender, self.conn.test_to], limit=limit)

    def note(self, text: object) -> None:
        self.notes.append(self.clean(text, 500))

    async def call(self, method: str, path: str, label: str, **kw: object) -> httpx.Response:
        if self.calls.sent >= self.calls.limit:
            raise _Fail("request_limit")
        self.calls.sent += 1
        start = time.perf_counter()
        r = await self.http.request(method, self.base + path, follow_redirects=False,
                                    headers={"Authorization": f"Bearer {self.conn.key}",
                                             "Accept": "application/json"}, **kw)
        ms = int((time.perf_counter() - start) * 1000)
        self.ms += ms
        self.note(f"[{self.calls.sent}] {method} {label}: HTTP {r.status_code} · {ms}ms · {len(r.content)}B")
        return r

    def expect(self, r: httpx.Response, *ok: int) -> dict:
        """기대한 상태면 JSON(dict)을, 아니면 오류 본문의 `code`(없으면 http_<상태>)로 실패."""
        if r.status_code in ok:
            try:
                data = r.json()
            except ValueError:
                raise _Fail("not_json") from None
            if not isinstance(data, dict):
                raise _Fail("not_object")
            return data
        code, error = None, None
        try:
            body = r.json()
            if isinstance(body, dict):
                code, error = body.get("code"), body.get("error")
        except ValueError:
            pass
        self.note(f"오류 code={code} · error={error}")
        if r.status_code == 429:
            self.note(f"Retry-After={r.headers.get('retry-after')}")
        raise _Fail(code if isinstance(code, str) and code else f"http_{r.status_code}")

    def result(self, step_id: str, ok: bool, detail: str) -> DiagnosticStep:
        return DiagnosticStep(id=step_id, label=LABELS[step_id], ok=ok, detail=self.clean(detail),
                              latency_ms=self.ms if self.calls.sent else None, notes=self.notes)

    def failed(self, step_id: str, exc: Exception) -> DiagnosticStep:
        # 통신 예외의 글에는 주소(Account ID)·키가 있을 수 있어 종류만 남긴다.
        return self.result(step_id, False, str(exc) if isinstance(exc, _Fail) else type(exc).__name__)


def _skipped(step_id: str, why: str) -> DiagnosticStep:
    return DiagnosticStep(id=step_id, label=LABELS[step_id], ok=False, detail=why, skipped=True)


async def check_senders(conn: DiagnosticConn, http: httpx.AsyncClient, *, calls: Calls | None = None) -> DiagnosticStep:
    """P1: 인증 + 발신번호 목록. 고른 발신번호(`conn.sender`)가 승인됐는지도 본다."""
    run = _Run(conn, http, calls)
    try:
        data = run.expect(await run.call("GET", "/sender-numbers", "sender-numbers"), 200)
        run.note(f"구조: {structure(data)}")
        rows = data.get("senderNumbers")
        if not isinstance(rows, list):
            raise _Fail("no_senderNumbers")
        mine = None
        for i, row in enumerate(rows[:20], 1):
            row = row if isinstance(row, dict) else {}
            same = bool(conn.sender) and _digits(row.get("number")) == _digits(conn.sender)
            mine = row.get("status") if same else mine
            run.note(f"#{i} status={row.get('status')}{' (= 고른 발신번호)' if same else ''}")
        counts = Counter(str(r.get("status")) for r in rows if isinstance(r, dict))
        if not conn.sender:
            ours = "발신번호를 고르지 않음"
        elif mine is None:
            ours = "고른 발신번호가 목록에 없음"
        else:
            ours = "고른 발신번호 승인됨" if mine == "approved" else f"고른 발신번호 {mine}"
        tally = " · ".join(f"{k} {v}" for k, v in sorted(counts.items()))
        return run.result("P1", True, f"발신번호 {len(rows)}개 · {tally} · {ours}" if tally else f"발신번호 0개 · {ours}")
    except Exception as e:  # noqa: BLE001 — 진단은 던지지 않는다
        return run.failed("P1", e)


async def check_send_sms(conn: DiagnosticConn, http: httpx.AsyncClient, *, send_test_sms: bool = False,
                         calls: Calls | None = None) -> tuple[DiagnosticStep, str | None]:
    """P2: `conn.test_to` 로 실제 문자 1건. `send_test_sms=True` 일 때만 보낸다. (결과, 제공사 messageId|None)."""
    if not send_test_sms:
        return _skipped("P2", "보내지 않음 — send_test_sms=True 일 때만 보냄"), None
    if not conn.sender or not conn.test_to:
        return _skipped("P2", "발신번호와 받을 번호가 모두 있어야 보냄"), None
    run = _Run(conn, http, calls)
    try:
        body = {"To": conn.test_to, "From": conn.sender, "Body": SMS_TEXT, "Type": "sms",
                "IdempotencyKey": f"chronos-probe-{uuid.uuid4().hex}"}
        r = await run.call("POST", "/messages", "messages", json=body)
        data = run.expect(r, 200, 201)
        run.note(f"구조: {structure(data)}")
        mid = data.get("messageId")
        if not isinstance(mid, str) or not mid:
            raise _Fail("no_messageId")
        return run.result("P2", True, f"HTTP {r.status_code} · status={data.get('status')} · "
                                      f"failureCode={data.get('failureCode')} · messageId 받음"), mid
    except Exception as e:  # noqa: BLE001
        return run.failed("P2", e), None


async def check_message_status(conn: DiagnosticConn, http: httpx.AsyncClient, message_id: str | None, *,
                               sleep: Sleep = asyncio.sleep, calls: Calls | None = None) -> DiagnosticStep:
    """P3: 보낸 문자의 상태를 5초 간격 최대 4번. sent·failed 가 되면 멈춘다. 끝까지 queued 면 실패(still_queued)."""
    if not message_id:
        return _skipped("P3", "보낸 시험 문자가 없음(P2 를 함께 돌려야 함)")
    run = _Run(conn, http, calls)
    try:
        seen: list[str] = []
        failure = None
        for i in range(POLL_TIMES):
            if i:
                await sleep(POLL_GAP_S)
            data = run.expect(await run.call("GET", f"/messages/{message_id}", "messages/{id}"), 200)
            status, failure = str(data.get("status")), data.get("failureCode")
            run.note(f"{i + 1}/{POLL_TIMES} status={status} · failureCode={failure}")
            if not seen or seen[-1] != status:
                seen.append(status)
            if status in FINAL:
                break
        path = " → ".join(seen)
        if seen[-1] not in FINAL:
            raise _Fail(f"still_{seen[-1]} · {path}")
        return run.result("P3", True, path + (f" · failureCode={failure}" if failure else ""))
    except Exception as e:  # noqa: BLE001
        return run.failed("P3", e)


async def check_received(conn: DiagnosticConn, http: httpx.AsyncClient, *, calls: Calls | None = None) -> DiagnosticStep:
    """P4: 받은 문자 목록 — 구조와 건수만(본문·번호는 남기지 않음)."""
    run = _Run(conn, http, calls)
    try:
        r = await run.call("GET", "/messages", "messages?status=received",
                           params={"status": "received", "pageSize": "20"})
        data = run.expect(r, 200)
        run.note(f"구조: {structure(data)}")
        rows = data.get("data")
        if not isinstance(rows, list):
            raise _Fail("no_data")
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        kinds = Counter(f"{x.get('direction')}/{x.get('status')}" for x in rows if isinstance(x, dict))
        return run.result("P4", True, f"{len(rows)}건 · meta.total={meta.get('total')} · "
                          + (" · ".join(f"{k} {v}" for k, v in sorted(kinds.items())) or "비어 있음"))
    except Exception as e:  # noqa: BLE001
        return run.failed("P4", e)


async def run_checks(conn: DiagnosticConn, http: httpx.AsyncClient, *, send_test_sms: bool = False,
                     steps: tuple[int, ...] = (1, 2, 3, 4), sleep: Sleep = asyncio.sleep,
                     calls: Calls | None = None) -> list[DiagnosticStep]:
    """고른 단계를 차례로. 기본(연결 테스트)은 문자를 보내지 않는다 — P2·P3 은 건너뜀으로 돌아온다."""
    calls = calls if calls is not None else Calls()
    out: list[DiagnosticStep] = []
    mid: str | None = None
    if 1 in steps:
        out.append(await check_senders(conn, http, calls=calls))
    if 2 in steps:
        result, mid = await check_send_sms(conn, http, send_test_sms=send_test_sms, calls=calls)
        out.append(result)
    if 3 in steps:
        out.append(await check_message_status(conn, http, mid, sleep=sleep, calls=calls))
    if 4 in steps:
        out.append(await check_received(conn, http, calls=calls))
    return out
