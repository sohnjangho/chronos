"""들어온 문자 응대(Task 84) — 일꾼(Task 71)이 저장하고 받기 판정(들어오는 문)을 마친 문자 가운데 engage·notice 인 것을 글
세션이 하네스 안에서 답한다. **판정·도구·뒤 확인을 새로 만들지 않는다 — 부르기만 한다**: 등급은 door.resolve·scope_of, 도구는
tools.Toolbox(toolsets.for_class 의 묶음), 쓴 글은 review.check, 나가기는 gate.dispatch 하나뿐이다.

handle(message_id) 한 건:
1. 잡기 — 받은 줄이 engage·notice(`admission` allowed · known_caller / unknown_accepted)이고 아직 잡히지 않았으면 그 줄의
   claimed_at 에 지금을 적는다(조건부 UPDATE 한 문장 — 같은 DB 의 두 일꾼·넘기기와 쓸기가 겹쳐도 한 번만 잡힌다). 받는 줄의
   claimed_at 은 「응대가 가져감」이다(나가는 줄의 「나가려고 차지함」과 같은 칸 — 받는 줄에서는 다른 코드가 읽지 않는다).
   받기 판정·수신 거부 처리는 일꾼이 이미 했다 — 여기서 다시 하지 않는다.
2. 상대가 보낸 지 STALE_S 가 지났으면 답하지 않는다(TOO_OLD). 등급을 번호로 다시 보고(door.resolve) 판정 때와 다르면 답하지
   않는다(CLASS_CHANGED — 그 사이 수신 거부·주소록이 바뀜). 범위 door.scope_of → 상자 Toolbox(묶음 for_class(등급, "sms")).
3. 글 세션(session_for)에 지시문(instructions.inbound) · 도구 정의 · 대화 기록(그 대화의 최근 HISTORY_LINES 줄, 번호를 가리고,
   상대 글은 PEER_LABEL 꼬리표의 자료) · box.call 을 준다. 한 문자에 WALL_S 초까지.
4. 글: notice 면 모델 글을 버리고 NOTICE_TEXT(kind notice), engage 면 모델 글(kind auto_reply, 한국어가 아니면 body_ko). 언어가
   연락처 언어와 다르면 언어 바꿈 제안(contact_proposals kind language — 같은 대화의 제안 상한 tools.MAX_PROPOSALS 안에서).
5. 뒤 확인 review.check(said=[글], peer_lines=[받은 글], tool_results=box.results, scope=box.scope). 예외면 깨끗하지 않음.
6. 답 줄(direction out · origin agent · reply_to_id · 연락처가 없으면 peer_number)을 draft 로 만들고 commit. 깨끗하면
   gate.dispatch(…, tools.AGENT) — 「승인 받기」면 문이 초안(needs_approval)으로 두고, 「위임」이면 나간다. 깨끗하지 않으면
   보내지 않고 fail_reason HELD_REASON + `held_for_review`(blocked, detail 은 깃발 이름).

끝나는 모든 길은 줄에 정해진 상태를 남긴다: 답 줄(나감·초안·확인 뒤 보내기) 또는 받은 줄의 `reply_failed`(noted, 까닭 글).
잡지 않은 줄(record·stop·없는 줄·이미 잡힌 줄)은 건드리지 않는다. 예외는 종류만 로그에 남기고 그 줄만 끝낸다. 취소되면 까닭
INTERRUPTED 를 남기고 다시 올린다. 프로세스가 죽어 잡힌 채 남은 줄은 쓸기(inbox)가 CLAIM_STALE_S 뒤 INTERRUPTED 로 닫는다.
같은 번호의 문자는 이 프로세스 안에서 차례로 답한다(_turn — 도구의 대화당 상한을 두 상자가 동시에 세지 않게).
자동 답 상한·답 유예·모르는 번호 안내 횟수는 여기서 세지 않는다 — 들어오는 문과 나가는 문이 센다.
번호는 지시문·대화 기록에 넣지 않는다(가리개 hide_phones 는 둘째 줄이다 — 주소록 번호는 어디에도 싣지 않는다).
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app import db
from app.outreach import languages, redact, site_name
from app.outreach.harness import door, events, gate, review, tools, toolsets
from app.outreach.harness.types import CallerClass, Ref, Scope
from app.outreach.text import instructions
from app.outreach.text import session as text_session
from app.outreach.text.session import LANGUAGE, PEER_LABEL, TextFailed, TextUsage
from app.store import outreach
from app.store.tables_outreach import ContactProposal, OutreachMessage
from app.store.timeutil import as_utc

logger = logging.getLogger(__name__)

NOTICE_TEXT = "담당자가 확인 후 연락드리겠습니다."  # 모르는 번호의 고정 안내(kind notice)
HELD_REASON = "내용 확인 필요"  # 뒤 확인에 걸린 답 초안의 fail_reason(화면의 「확인 뒤 보내기」)
WALL_S = 90.0  # 한 문자 응대(글 세션 + 도구)의 실제 시간 상한
STALE_S = 3600  # 상대가 보낸 지 이만큼 지난 문자는 자동으로 답하지 않는다
CLAIM_STALE_S = 600  # 잡힌 채 답도 까닭도 없이 이만큼 지난 줄은 멈춘 응대로 본다(쓸기가 닫는다) — WALL_S 보다 넉넉히
HISTORY_LINES = 6  # 대화 기록 줄 수(이번 문자 포함)
HISTORY_CHARS = 500  # 대화 기록 한 줄의 글자
VERDICTS = {"known_caller": "engage", "unknown_accepted": "notice"}  # 문자의 admission allowed detail → 받기 판정
AUTO_KINDS = door.AUTO_KINDS
# reply_failed 의 까닭(detail)
MODEL_FAILED = "모델이 답을 만들지 못함"
TIME_LIMIT = "시간 상한을 넘김"
TOO_OLD = "받은 지 오래된 문자라 자동으로 답하지 않음"
CLASS_CHANGED = "받은 뒤 등급이 바뀜"
INTERRUPTED = "응대가 중간에 멈춤"
EMPTY = "모델의 답이 비어 있음"
CHECK_BROKE = "뒤 확인을 마치지 못함"  # held_for_review 의 detail(깃발 대신)

_M = OutreachMessage
_turns: dict[str, list] = {}  # 번호 → [잠금, 쓰는 수] (쓰는 쪽이 없으면 지운다)


@dataclass(frozen=True)
class _Prep:
    verdict: str
    caller_class: CallerClass
    scope: Scope
    names: frozenset[str]


@dataclass(frozen=True)
class _Inputs:
    site: str | None
    name: str | None
    language: str
    request: str | None
    history: list[dict]
    reference: dict[str, str]


def _now() -> datetime:
    return datetime.now(UTC)


def _db():
    return contextmanager(db.get_session)()


def verdict_of(log: object) -> str | None:
    """받은 문자 줄의 사건에서 받기 판정: engage · notice, 그 밖은 None(응대하지 않는다)."""
    for event in log if isinstance(log, list) else []:
        if isinstance(event, dict) and event.get("rule") == "admission" and event.get("verdict") == "allowed":
            return VERDICTS.get(event.get("detail"))
    return None


def _engaged(row: OutreachMessage | None) -> bool:
    return (row is not None and row.direction == "in" and row.channel == "sms" and row.origin == "peer"
            and row.status == "received" and row.caller_class is not None and verdict_of(row.harness_json) is not None)


# ── 한 건 ─────────────────────────────────────────────────────────────


async def handle(message_id: int, *, now: datetime | None = None) -> None:
    """받은 문자 한 건에 답한다(모듈 머리 글). now 는 시험·대본의 시각(없으면 지금). 예외를 올리지 않는다(취소만 올린다)."""
    fixed = None if now is None else as_utc(now)
    clock: Callable[[], datetime] = (lambda: fixed) if fixed is not None else _now
    try:
        key = await asyncio.to_thread(_peer_key, message_id)
    except Exception as exc:  # noqa: BLE001 — 잡기 전이라 줄은 그대로 남고 다음 쓸기가 다시 본다
        logger.warning("들어온 문자를 읽지 못했습니다 (%s)", type(exc).__name__)
        return
    if key is None:
        return
    async with _turn(key):
        try:
            claimed = await asyncio.to_thread(_claim, message_id, clock())
        except Exception as exc:  # noqa: BLE001 — 잡지 못했으니 줄은 그대로 — 다음 쓸기가 다시 본다
            logger.warning("들어온 문자를 잡지 못했습니다 (%s)", type(exc).__name__)
            return
        if not claimed:
            return
        try:
            await _answer(message_id, clock, fixed)
        except Exception as exc:  # noqa: BLE001 — 한 건의 고장이 다음 건을 막지 않는다. 예외 글(번호가 있을 수 있다)은 싣지 않는다
            logger.warning("들어온 문자 응대가 오류로 끝났습니다 (%s)", type(exc).__name__)
            await asyncio.to_thread(_fail, message_id, f"오류({type(exc).__name__})", clock())
        except BaseException:  # 취소 — 까닭을 남기고(짧은 쓰기 한 번, 루프에서) 그대로 올린다
            try:
                _fail(message_id, INTERRUPTED, clock())
            except Exception as exc:  # noqa: BLE001 — 남기지 못하면 쓸기가 닫는다
                logger.info("멈춘 응대의 까닭을 남기지 못했습니다 (%s)", type(exc).__name__)
            raise


@asynccontextmanager
async def _turn(key: str) -> AsyncIterator[None]:
    """같은 번호의 문자는 차례로(이 프로세스 안). 쓰는 쪽이 없어지면 잠금을 지운다(쌓이지 않게)."""
    entry = _turns.setdefault(key, [asyncio.Lock(), 0])
    entry[1] += 1
    try:
        async with entry[0]:
            yield
    finally:
        entry[1] -= 1
        if entry[1] == 0 and _turns.get(key) is entry:
            del _turns[key]


async def _answer(message_id: int, clock: Callable[[], datetime], fixed: datetime | None) -> None:
    prep = await asyncio.to_thread(_prepare, message_id, clock())
    if prep is None:
        return
    if isinstance(prep, str):
        await asyncio.to_thread(_fail, message_id, prep, clock())
        return
    box = tools.Toolbox(prep.scope, "sms", Ref("message", message_id), names=prep.names, caller_class=prep.caller_class,
                        clock=clock)
    given = await asyncio.to_thread(_inputs, box, message_id)
    if given is None:
        return
    prompt = instructions.inbound(prep.caller_class, given.site, given.name, given.language, given.request,
                                  reference=given.reference, facts=prep.scope.grant_facts)
    with Session(db._engine) as llm_session:  # LLM 배정을 읽기만 한다(쓰기를 쥐지 않는다)
        chosen = text_session.session_for(llm_session)
        try:
            async with asyncio.timeout(WALL_S):
                reply = await chosen.respond(prompt, toolsets.tool_defs(prep.names), given.history, box.call)
        except TextFailed as failed:
            await asyncio.to_thread(_usage, message_id, failed.usage)
            await asyncio.to_thread(_fail, message_id, MODEL_FAILED, clock())
            return
        except TimeoutError:
            await asyncio.to_thread(_fail, message_id, TIME_LIMIT, clock())
            return
    await asyncio.to_thread(_usage, message_id, reply.usage)
    if prep.verdict == "notice":
        body, body_ko, kind = NOTICE_TEXT, None, "notice"
    else:
        body, kind = reply.text.strip(), "auto_reply"
        body_ko = reply.text_ko if reply.language.split("-")[0].lower() != "ko" else None
        if not body:
            await asyncio.to_thread(_fail, message_id, EMPTY, clock())
            return
    clean, flags = await asyncio.to_thread(_review, message_id, body, box, prep.caller_class, clock())
    reply_id = await asyncio.to_thread(_write_reply, message_id, box, body, body_ko, kind, reply.language, clean, flags,
                                       clock())
    if reply_id is not None and clean:
        await gate.dispatch("message", reply_id, tools.AGENT, now=fixed)


# ── DB 묶음(스레드에서, 묶음마다 새 세션 — 모델·문을 부르는 동안 쥐지 않는다) ──────


def _peer_key(message_id: int) -> str | None:
    with _db() as session:
        row = session.get(_M, message_id)
        if row is None:
            return None
        return row.peer_number or f"row:{message_id}"


def _claim(message_id: int, at: datetime) -> bool:
    """응대할 줄이면 잡는다 — 조건부 UPDATE 한 문장이라 둘이 동시에 잡아도 하나만 참."""
    with _db() as session:
        if not _engaged(session.get(_M, message_id)):
            return False
        done = session.execute(update(_M).where(_M.id == message_id, _M.claimed_at.is_(None)).values(claimed_at=at))
        session.commit()
        return done.rowcount == 1


def _prepare(message_id: int, at: datetime) -> _Prep | str | None:
    """등급·범위·묶음. 답하지 않을 까닭이면 그 글, 줄이 사라졌으면 None."""
    with _db() as session:
        row = session.get(_M, message_id)
        if row is None:
            return None
        verdict = verdict_of(row.harness_json)
        if verdict is None:  # 잡을 때 본 판정이 사라짐(사건 칸이 바뀜) — 답하지 않는다
            return CLASS_CHANGED
        sent = min(as_utc(t) for t in (row.sent_at, row.created_at) if t is not None)
        if at - sent > timedelta(seconds=STALE_S):
            return TOO_OLD
        caller = door.resolve(session, row.peer_number, now=at)
        if caller.caller_class != row.caller_class:
            return CLASS_CHANGED
        scope = door.scope_of(session, caller)
        return _Prep(verdict, caller.caller_class, scope, toolsets.for_class(caller.caller_class, "sms"))


def _hidden(text: str | None, limit: int) -> str:
    return redact.hide_phones(text or "")[:limit]  # 가린 뒤 자른다(잘린 번호 조각이 남지 않게)


def _inputs(box: tools.Toolbox, message_id: int) -> _Inputs | None:
    """지시문 칸과 대화 기록. 현장·이름은 범위가 한 현장·한 사람으로 정해졌을 때만(모르는 번호에게는 아무것도)."""
    with _db() as session:
        row = session.get(_M, message_id)
        if row is None:
            return None
        person = box.person(session)
        site = site_name.spoken(session, box.sid) or None  # 부를 이름(없으면 날짜·판 표시를 뗀 이름)
        asked = session.get(_M, row.reply_to_id) if row.reply_to_id is not None else None
        request = asked.body if asked is not None and asked.direction == "out" else None
        return _Inputs(site, person.name if person is not None else None,
                       person.language if person is not None else "ko", request, _history(session, row),
                       site_name.reference(session, box.sid) if site else {})


def _history(session: Session, row: OutreachMessage) -> list[dict]:
    """그 대화의 최근 HISTORY_LINES 줄(이번 문자까지, 오래된 것부터): 받은 글과 나간 글. 번호를 가린다."""
    if row.contact_id is not None:
        same = _M.contact_id == row.contact_id
    elif row.peer_number is not None:
        same = _M.peer_number == row.peer_number
    else:
        same = _M.id == row.id
    shown = or_(and_(_M.direction == "in", _M.status == "received"),
                and_(_M.direction == "out", _M.status.in_(outreach.SENT_MESSAGE)))
    rows = session.scalars(select(_M).where(same, shown, _M.id <= row.id).order_by(_M.id.desc()).limit(HISTORY_LINES))
    out = []
    for line in reversed(list(rows)):
        if line.direction == "in":
            out.append({"role": "peer", "label": PEER_LABEL, "text": _hidden(line.body, HISTORY_CHARS)})
        else:
            out.append({"role": "ours", "text": _hidden(line.body, HISTORY_CHARS)})
    return out


def _review(message_id: int, body: str, box: tools.Toolbox, caller_class: CallerClass, at: datetime) -> tuple[bool, list]:
    """뒤 확인 — (깨끗한가, 깃발). 예외면 깨끗하지 않음(깃발 없음 — CHECK_BROKE)."""
    with _db() as session:
        try:
            row = session.get(_M, message_id)
            peer = [] if row is None else [row.body]
            verdict = review.check(session, Ref("message", message_id), said=[body], peer_lines=peer,
                                   tool_results=list(box.results), scope=box.scope, caller_class=caller_class, now=at)
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.warning("뒤 확인을 마치지 못했습니다 (%s)", type(exc).__name__)
            return False, []
        return verdict.clean is True, list(verdict.flags)


def _write_reply(message_id: int, box: tools.Toolbox, body: str, body_ko: str | None, kind: str, language: str,
                 clean: bool, flags: list, at: datetime) -> int | None:
    """답 줄을 초안으로 만든다(깨끗하지 않으면 「확인 뒤 보내기」). 언어 바꿈 제안도 같은 묶음. 받은 줄이 사라졌으면 None."""
    with _db() as session:
        asked = session.get(_M, message_id)
        if asked is None:
            return None
        made = OutreachMessage(
            schedule_id=asked.schedule_id, contact_id=asked.contact_id,
            peer_number=None if asked.contact_id is not None else asked.peer_number, direction="out", channel="sms",
            kind=kind, body=body, body_ko=body_ko, origin="agent", origin_name=tools.AGENT_NAME, status="draft",
            reply_to_id=message_id, fail_reason=None if clean else HELD_REASON, created_at=at)
        session.add(made)
        session.flush()
        if not clean:
            events.record(session, Ref("message", made.id), "held_for_review", "blocked",
                          ", ".join(flags) if flags else CHECK_BROKE, now=at)
        if kind == "auto_reply":
            _propose_language(session, box, language, at)
        session.commit()
        return made.id


def _propose_language(session: Session, box: tools.Toolbox, language: str, at: datetime) -> None:
    """답한 언어가 그 연락처의 언어와 다르면 언어 바꿈 제안(사람이 승인해야 주소록이 바뀐다). 같은 제안이 기다리는 중이면 더
    만들지 않는다. 대화의 제안 상한은 도구 상자의 것을 쓴다."""
    person = box.person(session)
    if person is None or not LANGUAGE.fullmatch(language or ""):
        return
    if language.split("-")[0].lower() in {(person.language or "ko").split("-")[0].lower(), languages.text_language(person.language)}:
        return  # 문자로 쓰는 언어로 답한 것(중국어 상대에게 영어)도 바꿈 제안이 아니다
    waiting = select(ContactProposal.id).where(ContactProposal.kind == "language", ContactProposal.contact_id == person.id,
                                               ContactProposal.language == language[:10], ContactProposal.status == "pending")
    if session.scalar(waiting.limit(1)) is not None or not box.room(session, ContactProposal, tools.MAX_PROPOSALS):
        return
    session.add(ContactProposal(schedule_id=box.sid, kind="language", contact_id=person.id, language=language[:10],
                                created_at=at, **box.link()))


def _usage(message_id: int, usage: TextUsage | None) -> None:
    if usage is None:
        return
    with _db() as session:
        outreach.add_usage(session, "text_reply", ref=("message", message_id), model=usage.model,
                           input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, cost=usage.cost)
        session.commit()


def answered(session: Session, message_id: int) -> bool:
    """그 받은 문자에 끝이 났는가 — 답 줄(자동 답·고정 안내)이 있거나 reply_failed 가 남았다."""
    made = select(_M.id).where(_M.reply_to_id == message_id, _M.direction == "out", _M.origin == "agent",
                               _M.kind.in_(AUTO_KINDS))
    if session.scalar(made.limit(1)) is not None:
        return True
    row = session.get(_M, message_id)
    log = row.harness_json if row is not None and isinstance(row.harness_json, list) else []
    return any(isinstance(event, dict) and event.get("rule") == "reply_failed" for event in log)


def _fail(message_id: int, reason: str, at: datetime) -> None:
    """답하지 못한 까닭을 받은 줄에 남긴다(이미 끝난 줄이면 아무것도 하지 않는다 — 한 번만)."""
    with _db() as session:
        if session.get(_M, message_id) is None or answered(session, message_id):
            return
        events.record(session, Ref("message", message_id), "reply_failed", "noted", reason, now=at)
        session.commit()
