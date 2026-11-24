"""「관리 포인트가 바뀌었습니다」 카드(계획 5 Task 5): 차이를 적어 두고, 새 포인트의 바깥 위험을 뒤에서 찾고, 카드 꼴을 짓는다.

- 표 point_cards: (일정, 버전, what_if) 한 줄. what_if = 지연 분석의 가정 포인트(버전은 그때의 지금 버전 — 덮어쓴다).
  차이를 사람이 읽을 꼴(new·tightened·removed — 이름·여유는 엔진 값 그대로)과 그때의 포인트, 위험 찾기 상태·결과를 둔다.
- 「새 포인트」 = added + became_critical(ES 순, points_max_new 개까지). 바깥 위험(app.points.risk.look)은 이것만 찾는다.
  찾기는 응답을 막지 않는 뒤 작업이다: 버전 저장은 commit 이 된 뒤(after_commit), 지연 분석·points.check 는 commit 뒤 바로.
  찾는 동안 risk_status 는 looking(「바깥 위험 찾는 중」). look 약속대로 앞뒤로 commit 한다. 같은 차이를 다시 적으면(같은
  내용) 찾은 것·실패한 것을 그대로 둔다 — 다시 부르지 않는다(바깥 호출은 돈이 든다). 실패·멈춘 찾기를 다시 하는 것은 사람의
  「다시 찾기」(retry)뿐이다. 새 버전·새 가정 차이는 새로 찾는다.
- 빠진 포인트에는 까닭을 붙인다: 여유가 늘어남(relief) · 창 밖으로 밀림(out_of_window — ES 가 Data Date + w주 뒤로, 완화가
  아니다) · 끝남(finished) · 일정에서 빠짐(gone).
- 카드(payload)는 added·became_critical·tightened 가 하나라도 있을 때만(없으면 None — 다 끝난 일정·바뀜 없음은 카드 없음).
  위험은 포인트마다 묶고, 건너뛴 것(skipped)은 따로 모은다(화면은 「건너뛴 자료 n개」로 접는다). 근거 문장 상태는 quotes.get
  으로 읽기만 한다 — 채우기(fill)는 사람이 [근거 문장 보기]를 누른 API 에서만. 근거 문장 열쇠의 kind 칸은 「갈래:질문 지문」
  (quote_kind — 가정 여부와 질문 글의 해시)이라, 가정 줄·버전 줄·위험 줄이 바뀐 질문은 옛 문장을 다시 쓰지 않는다.
- 질문 글(quote_question)에는 바깥 글(업체 소식 제목)을 넣지 않는다 — 업체 갈래는 코드가 지은 말만.
- 번호·키는 어디에도 없다. 실패 로그는 종류만.
"""

import asyncio
import hashlib
import json
import logging
import threading
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import JSON, event
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.cpm import CpmResult
from app.core.model import Schedule
from app.core.points import Point, PointsDiff
from app.points import quotes
from app.store.settings import points_config
from app.store.tables import Base, ScheduleRecord
from app.store.tables_outreach import UtcDateTime
from app.store.timeutil import as_utc

logger = logging.getLogger(__name__)

LOOKING, DONE, FAILED, NOTHING, NOT_STARTED = "looking", "done", "failed", "none", "not_started"
RISK_MESSAGES = {LOOKING: "바깥 위험 찾는 중", DONE: "", FAILED: "바깥 위험을 찾지 못했습니다", NOTHING: "",
                 NOT_STARTED: "바깥 위험을 아직 찾지 않았습니다"}
# 뒤 작업을 띄울 수 있는가: 서버가 도는 동안만(app.main lifespan 이 켜고 끈다). 씨앗·명령줄(python -m app.seed …)은 프로세스가
# 곧 끝나 찾기가 「찾는 중」으로 멈추므로, 거기서 적은 줄은 not_started 로 두고 사람이 [바깥 위험 찾기](retry)로 처음 찾는다.
SERVING = False
STALE_AFTER = timedelta(minutes=15)  # 이보다 오래 찾는 중이면 멈춘 것(서버가 다시 켜짐 등) — failed 로 보인다
REASONS = {"relief": "여유가 늘어남", "out_of_window": "창 밖으로 밀림", "finished": "끝남", "gone": "일정에서 빠짐"}
POINT_ACTIONS = ("contact", "recovery")  # [담당자에게 확인 연락] · [만회안 보기]


class PointCard(Base):
    __tablename__ = "point_cards"

    schedule_id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    what_if: Mapped[bool] = mapped_column(primary_key=True)
    data_json: Mapped[dict] = mapped_column(JSON)  # {basis, new, more, tightened, removed, diff, trigger}
    points_json: Mapped[list] = mapped_column(JSON)  # 그때의 포인트(store.points 꼴)
    risk_status: Mapped[str]
    risks_json: Mapped[list] = mapped_column(JSON, default=list)  # [asdict(risk.Risk)]
    generation: Mapped[int] = mapped_column(default=0)  # 다시 적을 때마다 +1 — 늦게 끝난 옛 찾기가 덮어쓰지 않게
    changed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)  # 이 차이를 처음 적은 때(주의할 일정의 「최근」)
    outdoor_json: Mapped[dict] = mapped_column(JSON, default=dict)  # 액티비티 → 실외 작업인가(LLM weather_sensitive, 고른 것만)
    shown_generation: Mapped[int] = mapped_column(default=0)  # 옛 칸(쓰지 않음 — 이미 만든 DB 의 NOT NULL 때문에 둔다)
    shown_json: Mapped[dict] = mapped_column(JSON, default=dict)  # 대화(chat_session_id) → 카드를 낸 차이 지문(shown_mark)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)


def point_json(p: Point) -> dict:
    return {"activity_id": p.activity_id, "name": p.name, "critical": p.critical, "tf": p.tf,
            "es": p.es.isoformat(), "ef": p.ef.isoformat()}


def _from_json(d: dict) -> Point:
    return Point(d["activity_id"], d["name"], d["critical"], d["tf"], date.fromisoformat(d["es"]),
                 date.fromisoformat(d["ef"]))


def diff_json(diff: PointsDiff) -> dict:
    return {"added": [point_json(p) for p in diff.added], "removed": list(diff.removed),
            "tightened": [list(t) for t in diff.tightened], "became_critical": list(diff.became_critical),
            "before_tf": dict(diff.before_tf)}


def new_points(diff: PointsDiff, points: Sequence[Point]) -> list[Point]:
    """added + became_critical, ES 순(같으면 포인트 차례)."""
    ids = {p.activity_id for p in diff.added} | set(diff.became_critical)
    return [p for p in points if p.activity_id in ids]  # points 는 이미 ES 순


def _removed(ids: Sequence[str], before: Mapping[str, Point], ready: Schedule, cpm: CpmResult, window_weeks: int
             ) -> list[dict]:
    edge = (ready.data_date or ready.start) + timedelta(weeks=window_weeks)
    acts = {a.id: a for a in ready.activities}
    out = []
    for i in ids:
        act, row, prev = acts.get(i), cpm.rows.get(i), before.get(i)
        if act is None or row is None:
            reason = "gone"
        elif act.actual_finish is not None:
            reason = "finished"
        elif row.es > edge:
            reason = "out_of_window"
        else:
            reason = "relief"
        item = {"activity_id": i, "name": prev.name if prev else (act.name if act else i), "reason": reason,
                "label": REASONS[reason]}
        if prev is not None:
            item["before_tf"] = prev.tf
        if row is not None and reason == "relief":
            item["tf"] = row.tf
        out.append(item)
    return out


def _data(session: Session, diff: PointsDiff, points: Sequence[Point], before: Mapping[str, Point], ready: Schedule,
          cpm: CpmResult) -> dict:
    cfg = points_config(session)
    fresh = new_points(diff, points)
    became = set(diff.became_critical)
    new = []
    for p in fresh[:cfg.max_new]:
        item = {**point_json(p), "became_critical": p.activity_id in became}
        if p.activity_id in diff.before_tf:  # 모르면 키 없음 — 화면은 「여유 n일 →」을 빼고 쓴다
            item["before_tf"] = diff.before_tf[p.activity_id]
        new.append(item)
    by_id = {p.activity_id: p for p in points}
    fresh_ids = {p.activity_id for p in fresh}
    tightened = [{**point_json(by_id[i]), "before_tf": a} for i, a, _ in diff.tightened
                 if i not in fresh_ids and i in by_id]
    return {"basis": {"tf_days": cfg.tf_days, "window_weeks": cfg.window_weeks}, "new": new,
            "more": max(0, len(fresh) - cfg.max_new), "tightened": tightened,
            "removed": _removed(diff.removed, before, ready, cpm, cfg.window_weeks), "diff": diff_json(diff)}


def changed(data: Mapping) -> bool:
    d = data["diff"]
    return bool(d["added"] or d["became_critical"] or d["tightened"])


def version_trigger(version: int) -> dict:
    return {"kind": "version", "from": version - 1, "to": version}


def _same(a: Mapping, b: Mapping) -> bool:
    return {k: v for k, v in a.items() if k != "trigger"} == {k: v for k, v in b.items() if k != "trigger"}


def remember(session: Session, schedule_id: int, version: int, *, what_if: bool, diff: PointsDiff,
             points: Sequence[Point], before: Mapping[str, Point], ready: Schedule, cpm: CpmResult,
             trigger: dict) -> bool:
    """차이를 적는다(flush 만). 뒤에서 바깥 위험을 찾아야 하면 True(새 포인트가 있고, 같은 차이를 이미 적은 적이 없음 —
    같은 차이면 찾은 것·찾는 중·실패를 그대로 두고 무엇을 바꿨는지(trigger)만 고친다).

    before = 앞 상태의 포인트(id → Point, 빠진 포인트의 이름·앞 여유). ready·cpm = 뒤 상태(빠진 까닭을 가른다).
    trigger = 카드 머리말: 버전 {kind: "version", from, to} | 지연 {kind: "delay", version, delay_ids, latest}.
    """
    data = {**_data(session, diff, points, before, ready, cpm), "trigger": trigger}
    stored = [point_json(p) for p in points]
    status = (LOOKING if SERVING else NOT_STARTED) if data["new"] else NOTHING
    row = session.get(PointCard, (schedule_id, version, what_if))
    now = datetime.now(UTC)
    if row is not None and _same(row.data_json, data) and row.points_json == stored:
        if row.data_json != data:
            row.data_json = data
            session.flush()
        return False
    if row is None:
        row = PointCard(schedule_id=schedule_id, version=version, what_if=what_if, generation=0, shown_generation=0)
        session.add(row)
    row.data_json, row.points_json, row.risk_status, row.risks_json = data, stored, status, []
    row.generation, row.updated_at, row.changed_at, row.outdoor_json = (row.generation or 0) + 1, now, now, {}
    session.flush()
    return status == LOOKING


def _chat(chat_session_id: int | None) -> str:
    return "-" if chat_session_id is None else str(chat_session_id)


def shown_mark(row: PointCard) -> str:
    """카드를 냈는지 견주는 지문: generation(차이) + 무엇을 바꿨는지(trigger — 새 지연이면 다르다)."""
    trigger = json.dumps(row.data_json.get("trigger"), sort_keys=True, ensure_ascii=False)
    return f"{row.generation}:{hashlib.sha1(trigger.encode()).hexdigest()[:8]}"


def shown(row: PointCard, chat_session_id: int | None) -> bool:
    """이 대화에 이 차이의 카드를 이미 냈는가(다른 대화·다른 사람은 따로)."""
    return (row.shown_json or {}).get(_chat(chat_session_id)) == shown_mark(row)


def mark_shown(row: PointCard, chat_session_id: int | None) -> None:
    row.shown_json = {**(row.shown_json or {}), _chat(chat_session_id): shown_mark(row)}


def status_of(row: PointCard) -> str:
    if row.risk_status == LOOKING and datetime.now(UTC) - as_utc(row.updated_at) >= STALE_AFTER:
        return FAILED
    return row.risk_status


def get(session: Session, schedule_id: int, version: int, *, what_if: bool) -> PointCard | None:
    return session.get(PointCard, (schedule_id, version, what_if))


def retry(session: Session, row: PointCard) -> bool:
    """사람의 「다시 찾기」·[바깥 위험 찾기]: 실패(멈춘 찾기 포함)했거나 아직 찾지 않은(not_started — 씨앗·명령줄에서 적은) 줄만
    찾는 중으로 바꾼다(flush 만 — commit 뒤 launch). 아니면 False."""
    if status_of(row) not in (FAILED, NOT_STARTED) or not row.data_json["new"]:
        return False
    row.risk_status, row.risks_json, row.updated_at = LOOKING, [], datetime.now(UTC)
    row.generation += 1
    session.flush()
    return True


def stored_points(row: PointCard) -> list[Point]:
    return [_from_json(d) for d in row.points_json]


# ── 뒤에서 바깥 위험 찾기 ─────────────────────────────────────────────

_tasks: set = set()  # 끝나기 전에 사라지지 않게 쥔다(asyncio 작업·스레드)


def _engine():
    from app.db import (
        current_engine,  # app.db 가 이 모듈을 import 한다 — 돌림 import 를 피해 부를 때 읽는다
    )

    return current_engine()


async def look_now(schedule_id: int, version: int, what_if: bool) -> None:
    """그 줄의 새 포인트 바깥 위험을 찾아 적는다. 자기 세션을 쓴다(look 앞뒤 commit). 그 사이 다시 적혔으면(generation) 버린다."""
    from app.points import risk  # 무거운 import(LLM·바깥 자료)는 부를 때
    from app.store.schedules import load

    engine = _engine()
    if engine is None:
        return
    with Session(engine) as session:
        try:
            row = get(session, schedule_id, version, what_if=what_if)
            if row is None or row.risk_status != LOOKING:
                return
            generation = row.generation
            ids = {item["activity_id"] for item in row.data_json["new"]}
            chosen = [p for p in stored_points(row) if p.activity_id in ids]
            current = load(session, schedule_id)[2]
            session.commit()  # look 앞: 쌓인 쓰기 없이
            outdoor: dict[str, bool] = {}
            found = [] if current != version else await risk.look(session, schedule_id, version, chosen, outdoor)
            row = get(session, schedule_id, version, what_if=what_if)
            if row is None or row.generation != generation:
                session.commit()  # look 이 적은 근거 줄은 남긴다
                return
            row.risks_json, row.risk_status, row.updated_at = [asdict(r) for r in found], DONE, datetime.now(UTC)
            row.outdoor_json = outdoor
            session.commit()
        except Exception as exc:  # noqa: BLE001 — 뒤 작업은 상태를 끝내야 한다. 예외 글은 남기지 않는다
            logger.warning("관리 포인트 바깥 위험 찾기 실패: 일정 %s 버전 %s (%s)", schedule_id, version, type(exc).__name__)
            session.rollback()
            _mark_failed(session, schedule_id, version, what_if)


def _mark_failed(session: Session, schedule_id: int, version: int, what_if: bool) -> None:
    try:
        row = get(session, schedule_id, version, what_if=what_if)
        if row is not None and row.risk_status == LOOKING:
            row.risk_status, row.updated_at = FAILED, datetime.now(UTC)
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("관리 포인트 바깥 위험 실패 표시도 못 함 (%s)", type(exc).__name__)


def _start(job: Callable[[], Coroutine]) -> None:
    """뒤 작업을 띄운다: 이벤트 루프 안이면 그 루프의 작업, 밖(동기 API·스레드)이면 자기 루프를 가진 스레드.
    시험은 이 함수를 바꿔 끼운다(conftest — 바깥 호출 없음)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        task = loop.create_task(job())
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return

    def run() -> None:
        try:
            asyncio.run(job())
        finally:
            _tasks.discard(thread)

    thread = threading.Thread(target=run, name="points-risk", daemon=True)
    _tasks.add(thread)
    thread.start()


def launch(schedule_id: int, version: int, *, what_if: bool) -> None:
    """commit 이 끝난 뒤에 부른다."""
    _start(lambda: look_now(schedule_id, version, what_if))


_PENDING = "points_card_launch"  # session.info 의 열쇠: 바깥 commit 뒤에 띄울 (일정, 버전, what_if)


def launch_after_commit(session: Session, schedule_id: int, version: int, *, what_if: bool) -> None:
    """그 세션의 바깥 트랜잭션이 commit 된 뒤에 launch(버전 저장이 commit=False 로 부른 쪽 트랜잭션 안일 때도). SAVEPOINT
    commit 에는 띄우지 않고, 바깥 트랜잭션이 되돌려지면 띄우지 않는다(한 번만). 세션마다 듣는 것을 붙이지 않는다 — Session
    전체에 한 번 붙인 _fire·_drop 이 session.info 의 목록만 본다(쓰고 나면 비운다)."""
    session.info.setdefault(_PENDING, []).append((schedule_id, version, what_if))


@event.listens_for(Session, "after_commit")
def _fire(session: Session) -> None:
    if _PENDING not in session.info or session.in_nested_transaction():
        return
    for schedule_id, version, what_if in session.info.pop(_PENDING):
        launch(schedule_id, version, what_if=what_if)


@event.listens_for(Session, "after_transaction_end")
def _drop(session: Session, transaction) -> None:
    if transaction.parent is None:  # commit 이면 _fire 가 먼저 비웠다 — 되돌림이면 띄우지 않고 버린다
        session.info.pop(_PENDING, None)


# ── 카드·조회 꼴 ──────────────────────────────────────────────────────


def quote_json(state: quotes.QuoteState | None) -> dict | None:
    if state is None:
        return None
    return {"status": state.status, "message": state.message, "error_code": state.error_code,
            "quotes": [{"text": q.text, "url": q.url, "title": q.title} for q in state.quotes]}


BUSINESS_TOPIC = "담당 업체의 납기·공급 소식"


def quote_question(point: Mapping, kind: str, risks: Sequence[Mapping]) -> str | None:
    """Search Agent 에 물을 글. 그 포인트·갈래의 ok 줄이 없으면 None. 업체 갈래는 받은 제목을 넣지 않고 코드가 지은 말만
    (바깥 글이 지시로 들어가지 않게). 나머지 갈래의 줄은 코드가 숫자로 지은 것."""
    lines = [r["line"] for r in risks if r["activity_id"] == point["activity_id"] and r["kind"] == kind
             and r["status"] == "ok"]
    if not lines:
        return None
    topic = f"「{point['name']}」 작업 {BUSINESS_TOPIC}" if kind == "business" else " / ".join(lines)
    return (f"「{point['name']}」 작업({point['es']}~{point['ef']}) 기간에 영향을 줄 수 있는 다음 바깥 소식의 근거가 되는 "
            f"기사·자료 문장을 찾아 주세요: {topic}")


def quote_kind(kind: str, question: str, *, what_if: bool) -> str:
    """근거 문장 표 열쇠의 kind 칸: 「갈래:지문」(가정 여부와 질문 글 — 바뀌면 옛 문장을 쓰지 않는다)."""
    digest = hashlib.sha1(f"{int(what_if)}|{question}".encode()).hexdigest()[:8]
    return f"{kind}:{digest}"


def quote_states(session: Session, row: PointCard) -> dict[str, dict | None]:
    """'activity_id/kind' → 근거 문장 상태(아직 누르지 않았으면 None). ok 위험만. 읽기만 한다."""
    risks = row.risks_json or []
    points = {p["activity_id"]: p for p in row.points_json}
    out: dict[str, dict | None] = {}
    for r in risks:
        key = f"{r['activity_id']}/{r['kind']}"
        if r.get("status") != "ok" or key in out or r["activity_id"] not in points:
            continue
        question = quote_question(points[r["activity_id"]], r["kind"], risks)
        stored = quote_kind(r["kind"], question or "", what_if=row.what_if)
        out[key] = quote_json(quotes.get(session, row.schedule_id, row.version, r["activity_id"], stored))
    return out


def _risk_actions(r: Mapping) -> list[str]:
    if r.get("status") != "ok":
        return []
    return ["quote", "condition"] if r.get("kind") == "weather" else ["quote"]  # [조건으로 넣어 보기]는 날씨만


def payload(session: Session, row: PointCard, *, field: bool = False) -> dict | None:
    """chat 카드 card{kind: "points_changed", …}. 바뀜(added·became_critical·tightened)이 없으면 None.
    field = 보는(부른) 사람이 현장 관리자 — 연락처를 쓸 수 없으니 actions 에서 contact 를 뺀다. 새 포인트의 outdoor 는 바깥
    위험을 고를 때 LLM 이 정한 「실외 작업인가」(모르면 키 없음)."""
    data = row.data_json
    if not changed(data):
        return None
    status = status_of(row)
    risks = row.risks_json or []
    states = quote_states(session, row)
    names = {p["activity_id"]: p["name"] for p in row.points_json}
    owners = responsible(session, row.schedule_id, [i["activity_id"] for i in [*data["new"], *data["tightened"]]])
    actions = [a for a in POINT_ACTIONS if not (field and a == "contact")]
    outdoor = row.outdoor_json or {}
    new = []
    for item in data["new"]:
        mine = [{**r, "quote": states.get(f"{r['activity_id']}/{r['kind']}"), "actions": _risk_actions(r)}
                for r in risks if r["activity_id"] == item["activity_id"] and r["status"] != "skipped"]
        extra = {"outdoor": outdoor[item["activity_id"]]} if item["activity_id"] in outdoor else {}
        new.append({**item, **extra, "responsible": owners.get(item["activity_id"], []), "risks": mine,
                    "actions": list(actions)})
    skipped = [{"activity_id": r["activity_id"], "name": names.get(r["activity_id"], r["activity_id"]),
                "kind": r["kind"], "line": r["line"]} for r in risks if r["status"] == "skipped"]
    record = session.get(ScheduleRecord, row.schedule_id)
    return {
        "kind": "points_changed", "schedule_id": row.schedule_id, "version": row.version, "what_if": row.what_if,
        "domain": record.domain if record is not None else "", "trigger": data.get("trigger"),
        "basis": data["basis"], "new": new, "more": data["more"],
        "tightened": [{**t, "responsible": owners.get(t["activity_id"], []), "actions": list(actions)}
                      for t in data["tightened"]],
        "removed": data["removed"], "skipped": skipped, "skipped_count": len(skipped),
        "risk_status": status, "risk_message": RISK_MESSAGES[status],
        "risk_retry": status in (FAILED, NOT_STARTED),  # [다시 찾기] / not_started 면 [바깥 위험 찾기]
    }


def responsible(session: Session, schedule_id: int, activity_ids: Sequence[str]) -> dict[str, list[str]]:
    """작업 id → 담당 협력사 이름(숨긴 것 빼고, 이름 순). 하네스 facts.allowed_for 와 같은 규칙(공종 말·연결 기록).
    사람·번호는 없다 — 현장 관리자도 읽는 카드에 싣는다."""
    from app.outreach.harness import facts  # 돌림 import 를 피해 부를 때
    from app.outreach.redact import hide_phones
    from app.store import contacts

    wanted = set(activity_ids)
    out: dict[str, list[str]] = {}
    if not wanted:
        return out
    for firm, folks in contacts.listed(session, schedule_id):
        for aid in sorted(wanted & facts.allowed_for(session, schedule_id, [firm.id], [w.id for w in folks])):
            out.setdefault(aid, []).append(hide_phones(firm.name))
    return out
