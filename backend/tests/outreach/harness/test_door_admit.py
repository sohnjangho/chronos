"""들어오는 문(Task 66) — 받기 판정표(door.admit): 전화와 문자가 같은 표를 같은 차례로 지난다. 번호는 모두 가상이다.

문턱 숫자는 시험마다 limits_json 에 명시해 넣는다(기본값에 기대지 않는다).
"""

import ast
import inspect
import time
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.outreach import phone
from app.outreach.harness import door
from app.outreach.harness.types import ADMIT_REASONS, Caller
from app.store import outreach as store
from app.store.tables_outreach import OutreachCall, OutreachMessage
from tests.outreach.harness.test_door_class import (
    FOREIGN,
    KST,
    LANDLINE,
    NOW,
    OTHER_PHONE,
    REP_PHONE,
    account,
    block,
    company,
    connect,
    person,
    second_schedule,
)
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_PHONE

OTHER_DIGITS = "01000000000"
BURST = {"inbound_burst_count": 3, "inbound_burst_minutes": 5}
REPLIES = {"auto_reply_hourly": 2, "auto_reply_daily": 3}
ROOMY = {"inbound_burst_count": 99, "auto_reply_hourly": 99, "auto_reply_daily": 99, "unknown_notice_daily": 99,
         "unknown_calls_hourly": 99, "unknown_notice_total_daily": 99}  # 다른 줄을 볼 때 상한이 끼지 않게


def admit(session: Session, medium: str, number: str | None = SENTINEL_PHONE, *, now: datetime = NOW, **kw):
    return door.admit(session, medium, number, now=now, **kw)


def answer(session: Session, medium: str, number: str | None = SENTINEL_PHONE, **kw) -> tuple[str, str]:
    admitted = admit(session, medium, number, **kw)
    return admitted.verdict, admitted.reason


def rang(session: Session, at: datetime, **kw) -> OutreachCall:
    """받는 통화 줄 하나(받았든 거절했든 한 줄)."""
    row = OutreachCall(**{"direction": "in", "origin": "peer", "status": "completed", "created_at": at,
                          "peer_number": SENTINEL_DIGITS, **kw})
    session.add(row)
    session.flush()
    return row


def texted(session: Session, at: datetime, **kw) -> OutreachMessage:
    """들어온 문자 줄 하나(응대했든 기록만 했든 한 줄)."""
    row = OutreachMessage(**{"direction": "in", "channel": "sms", "origin": "peer", "body": "내일 가능합니다",
                             "status": "received", "created_at": at, "peer_number": SENTINEL_DIGITS, **kw})
    session.add(row)
    session.flush()
    return row


def replied(session: Session, at: datetime, *, claimed: bool = True, **kw) -> OutreachMessage:
    """그 번호 앞으로 만든 자동 답 하나(at 에 만듦). claimed=False 면 나가지 않은 초안(승인 받기) — 그래도 만든 것이다."""
    row = OutreachMessage(**{"direction": "out", "channel": "sms", "origin": "agent", "kind": "auto_reply",
                             "body": "확인했습니다", "status": "accepted" if claimed else "draft", "created_at": at,
                             "claimed_at": at if claimed else None, "peer_number": SENTINEL_DIGITS, **kw})
    session.add(row)
    session.flush()
    return row


def set_limits(session: Session, conn, **values) -> None:
    conn.limits_json = {**(conn.limits_json or {}), **values}
    session.flush()


# ── 결과의 꼴 ───────────────────────────────────────────────────────


def _situations(session: Session, sid: int) -> list[tuple[str, dict]]:
    """판정표의 모든 줄을 한 번씩 지나는 상황들: (번호, admit 인자)."""
    conn = connect(session, limits_json={**BURST, **REPLIES, "unknown_notice_daily": 1})
    person(session, company(session, sid))  # SENTINEL_PHONE = 연락처
    person(session, company(session, sid), "수거부", "010-0000-0003", do_not_contact=True)
    block(session, "01000000004")
    for _ in range(BURST["inbound_burst_count"]):
        rang(session, NOW, peer_number="01000000005")
    for _ in range(REPLIES["auto_reply_hourly"]):
        replied(session, NOW, peer_number="01000000006")
    assert conn.inbound_mode == "all"
    return [
        (SENTINEL_PHONE, {}), (SENTINEL_PHONE, {"live_calls": 1}), (SENTINEL_PHONE, {"body": "수신거부"}),
        (SENTINEL_PHONE, {"body": "[Web발신] 인증번호 0000"}), (SENTINEL_PHONE, {"has_media": True}),
        ("010-0000-0003", {}), ("010-0000-0004", {}), ("010-0000-0005", {}), ("010-0000-0006", {}),
        (OTHER_PHONE, {}), (None, {}),
    ]


def test_every_admit_verdict_carries_a_reason_code(session, sid):
    situations = _situations(session, sid)
    seen = set()
    for mode in ("off", "known", "all"):
        for test_mode in (False, True):
            conn = store.connection(session)
            conn.inbound_mode, conn.test_mode = mode, test_mode
            session.flush()
            for number, extra in situations:
                for medium in ("sms", "call"):
                    admitted = admit(session, medium, number, **extra)
                    assert isinstance(admitted, door.Admission) and isinstance(admitted.caller, Caller)
                    assert admitted.verdict in door.ADMIT_VERDICTS
                    assert admitted.reason in ADMIT_REASONS
                    assert admitted.confirm is (admitted.verdict == "stop")  # 여기 수신 거부 말은 연락처가 보냈다
                    assert SENTINEL_DIGITS not in repr(admitted) and "0199" not in repr(admitted)
                    seen.add(admitted.reason)
    assert seen == set(ADMIT_REASONS)  # 판정표의 열세 코드가 모두 나온다


def test_admission_takes_only_the_shared_words():
    caller = Caller("unknown", (), None)
    assert door.ADMIT_VERDICTS == ("engage", "notice", "record", "reject", "missed", "stop")
    plain = door.Admission("record", caller, "inbound_off")
    assert (plain.reason, plain.confirm) == ("inbound_off", False)
    for verdict, reason in (("engage", "모르는 번호"), ("engage", "known"), ("answer", "known_caller"), ("", "")):
        with pytest.raises(ValueError):
            door.Admission(verdict, caller, reason)
    with pytest.raises(TypeError):
        door.Admission("engage", "contact", "known_caller")
    assert door.Admission("stop", caller, "stop_word", confirm=True).confirm is True
    for verdict, reason, confirm in (("engage", "known_caller", True), ("record", "inbound_off", True),
                                     ("stop", "stop_word", 1), ("stop", "stop_word", None)):
        with pytest.raises(ValueError):  # 확인 문자는 수신 거부 말에만 — 참·거짓만
            door.Admission(verdict, caller, reason, confirm=confirm)


def test_admit_takes_only_the_two_media(session):
    connect(session)
    for medium in ("kakao", "", None):
        with pytest.raises(ValueError):
            admit(session, medium)


# ── 차례: 문자 표의 이웃한 줄마다 위가 이긴다 ────────────────────────
# 1 시험 모드 밖·차단 → 2 수신 거부 말 → 3 받지 않음 → 4 잦은 문자 → 5 자동 답 상한 → 6 기계 문자 → 7 사진
# → 8 수신 거부 번호 → 9 모르는 번호 → 10 응대


def _sms_rows(session: Session, sid: int, upper: str, lower: str) -> tuple[str | None, dict]:
    """문자 표의 두 줄(upper·lower)에 **함께** 걸리는 상황 하나를 차려 (번호, admit 인자)를 돌려준다."""
    rows = {upper, lower}
    conn = connect(session, inbound_mode="off" if "off" in rows else "all", limits_json=dict(ROOMY))
    number, extra = SENTINEL_PHONE, {"body": "내일 가능합니다"}
    if "dnc" in rows:
        store.mark_do_not_contact(session, SENTINEL_PHONE, reason="그만")  # 주소록에 없는 수신 거부 번호
    elif "unknown" not in rows:
        person(session, company(session, sid))  # 그 밖에는 연락처가 보낸다
    if "blocked" in rows:
        block(session, SENTINEL_DIGITS)
    if "outside" in rows:
        conn.test_mode, conn.allow_numbers_json = True, [OTHER_PHONE]
    if "stop" in rows:
        extra["body"] = "수신거부"
    if "burst" in rows:
        set_limits(session, conn, **BURST)
        for _ in range(BURST["inbound_burst_count"]):
            texted(session, NOW)
    if "replies" in rows:
        set_limits(session, conn, auto_reply_hourly=1)
        replied(session, NOW, claimed=False)
    if "machine" in rows:
        extra["body"] = "(광고) 자재 특가 안내"
    if "media" in rows:
        extra["has_media"] = True
    session.flush()
    return number, extra


@pytest.mark.parametrize("upper,lower,expected", [
    ("blocked", "stop", ("record", "blocked_number")),
    ("outside", "stop", ("record", "outside_test")),
    ("outside", "off", ("record", "outside_test")),
    ("stop", "off", ("stop", "stop_word")),
    ("stop", "burst", ("stop", "stop_word")),
    ("stop", "replies", ("stop", "stop_word")),
    ("off", "burst", ("record", "inbound_off")),
    ("burst", "replies", ("record", "burst_limit")),
    ("replies", "machine", ("record", "auto_reply_limit")),
    ("machine", "media", ("record", "machine_text")),
    ("media", "dnc", ("record", "media_attached")),
    ("dnc", "unknown", ("record", "do_not_contact")),  # 주소록에 없는 수신 거부 번호: 「모두」여도 안내를 보내지 않는다
])
def test_text_table_upper_row_wins(session, sid, upper, lower, expected):
    number, extra = _sms_rows(session, sid, upper, lower)
    assert answer(session, "sms", number, **extra) == expected


@pytest.mark.parametrize("row,expected", [
    ("blocked", ("record", "blocked_number")), ("outside", ("record", "outside_test")), ("stop", ("stop", "stop_word")),
    ("off", ("record", "inbound_off")), ("burst", ("record", "burst_limit")), ("replies", ("record", "auto_reply_limit")),
    ("machine", ("record", "machine_text")), ("media", ("record", "media_attached")),
    ("dnc", ("record", "do_not_contact")), ("unknown", ("notice", "unknown_accepted")),
    ("known", ("engage", "known_caller")),
])
def test_text_table_each_row_alone(session, sid, row, expected):
    """위 차례 시험이 뜻을 가지려면 줄 하나만 걸렸을 때 그 줄의 판정이 나와야 한다."""
    number, extra = _sms_rows(session, sid, row, row)
    assert answer(session, "sms", number, **extra) == expected


@pytest.mark.parametrize("upper,lower,expected", [
    ("blocked", "off", ("reject", "blocked_number")), ("off", "burst", ("reject", "inbound_off")),
    ("burst", "unknown_known_mode", ("reject", "burst_limit")), ("burst", "busy", ("reject", "burst_limit")),
    ("unknown_known_mode", "busy", ("reject", "unknown_not_accepted")),
    ("unknown_total", "busy", ("reject", "burst_limit")), ("dnc", "busy", ("missed", "line_busy")),
])
def test_call_table_upper_row_wins(session, sid, upper, lower, expected):
    rows = {upper, lower}
    mode = "off" if "off" in rows else "known" if "unknown_known_mode" in rows else "all"
    conn = connect(session, inbound_mode=mode, limits_json=dict(ROOMY))
    number = OTHER_PHONE if rows & {"unknown_known_mode", "unknown_total"} else SENTINEL_PHONE
    person(session, company(session, sid), do_not_contact="dnc" in rows)
    if "blocked" in rows:
        block(session, SENTINEL_DIGITS)
    if "burst" in rows:
        set_limits(session, conn, **BURST)
        for _ in range(BURST["inbound_burst_count"]):
            rang(session, NOW, peer_number=phone.normalize(number))
    if "unknown_total" in rows:
        set_limits(session, conn, unknown_calls_hourly=1)
        rang(session, NOW, peer_number="01000000009", caller_class="unknown")
    live = door.MAX_LIVE_CALLS if "busy" in rows else 0
    assert answer(session, "call", number, live_calls=live) == expected


# ── 1 시험 모드 밖 · 차단 ────────────────────────────────────────────


def test_outside_test_mode_is_rejected_or_only_recorded(session, sid):
    connect(session, test_mode=True, allow_numbers_json=[OTHER_PHONE], limits_json=BURST)
    person(session, company(session, sid))
    assert answer(session, "call") == ("reject", "outside_test")
    assert answer(session, "sms", body="수신거부") == ("record", "outside_test")
    assert answer(session, "call", None) == ("reject", "outside_test")
    assert answer(session, "call", OTHER_PHONE) == ("engage", "unknown_accepted")  # 허용 번호는 등급대로


def test_test_mode_allow_list_admits_the_listed_contact(session, sid):
    connect(session, test_mode=True, allow_numbers_json=[SENTINEL_PHONE], inbound_mode="known")
    person(session, company(session, sid))
    assert answer(session, "call") == ("engage", "known_caller")
    assert answer(session, "sms", body="내일 가능합니다") == ("engage", "known_caller")
    assert answer(session, "call", OTHER_PHONE) == ("reject", "outside_test")


def test_blocked_number_is_rejected_or_only_recorded(session, sid):
    connect(session)
    person(session, company(session, sid))
    block(session, SENTINEL_DIGITS)
    assert answer(session, "call") == ("reject", "blocked_number")
    assert answer(session, "sms", body="수신거부", has_media=True) == ("record", "blocked_number")


def test_no_connection_is_test_mode_so_nothing_is_taken(session, sid):
    """알림 연결이 없으면 시험 모드로 본다 — 모든 번호가 outside_test 이고 수신 거부 말도 기록만 한다."""
    person(session, company(session, sid))
    assert answer(session, "call") == ("reject", "outside_test")
    assert answer(session, "sms", body="내일 가능합니다") == ("record", "outside_test")
    assert answer(session, "sms", body="수신거부") == ("record", "outside_test")


# ── 3 받는 범위 「받지 않음」 ─────────────────────────────────────────


def test_mode_off(session, sid):
    connect(session, inbound_mode="off")
    account(session, "admin", OTHER_PHONE)
    person(session, company(session, sid))
    for number in (SENTINEL_PHONE, OTHER_PHONE, "010-0000-0009", None):
        assert answer(session, "call", number) == ("reject", "inbound_off")
        assert answer(session, "sms", number, body="내일 가능합니다", has_media=True) == ("record", "inbound_off")


def test_an_unknown_mode_value_is_off(session, sid):
    connect(session, inbound_mode="everything")
    person(session, company(session, sid))
    assert answer(session, "call") == ("reject", "inbound_off")
    assert answer(session, "sms", body="내일 가능합니다") == ("record", "inbound_off")


# ── 4 되풀이: 들어온 것을 센다 ──────────────────────────────────────


def test_five_calls_in_ten_minutes_then_reject(session, sid):
    connect(session, limits_json={"inbound_burst_count": 5, "inbound_burst_minutes": 10})
    row = person(session, company(session, sid))
    verdicts = []
    for minute in range(7):  # 1분에 한 번씩 일곱 번
        at = NOW + timedelta(minutes=minute)
        admitted = admit(session, "call", now=at)
        verdicts.append((admitted.verdict, admitted.reason))
        rang(session, at, peer_number=None, contact_id=row.id, schedule_id=sid,
             status="completed" if admitted.verdict == "engage" else "rejected")
    assert verdicts == [("engage", "known_caller")] * 5 + [("reject", "burst_limit")] * 2  # 여섯 번째부터
    # 줄은 0~6분에 일곱 개. 12분에는 지난 10분(2~6분)에 다섯 개가 남아 아직 거절, 그 뒤로는 넷 아래라 풀린다
    assert answer(session, "call", now=NOW + timedelta(minutes=12)) == ("reject", "burst_limit")
    assert answer(session, "call", now=NOW + timedelta(minutes=12, seconds=1)) == ("engage", "known_caller")
    assert answer(session, "call", now=NOW + timedelta(minutes=16, seconds=1)) == ("engage", "known_caller")  # 10분 뒤


def test_burst_threshold_and_window_edges(session, sid):
    conn = connect(session, limits_json=BURST)  # 5분에 3번
    person(session, company(session, sid))
    edge = NOW - timedelta(minutes=5)
    rang(session, edge)
    rang(session, NOW - timedelta(minutes=1))
    assert answer(session, "call") == ("engage", "known_caller")  # 두 번 — 문턱 아래
    rang(session, NOW)
    assert answer(session, "call") == ("reject", "burst_limit")  # 세 번 — 꼭 5분 전의 줄까지 센다
    assert answer(session, "call", now=NOW + timedelta(seconds=1)) == ("engage", "known_caller")  # 5분을 넘긴 줄은 뺀다
    set_limits(session, conn, inbound_burst_count=2)  # 설정을 바꾸면 다음 판정부터
    assert answer(session, "call", now=NOW + timedelta(seconds=1)) == ("reject", "burst_limit")
    set_limits(session, conn, inbound_burst_count=3, inbound_burst_minutes=6)
    assert answer(session, "call", now=NOW + timedelta(seconds=1)) == ("reject", "burst_limit")


def test_burst_counts_only_inbound_calls_of_that_number(session, sid):
    connect(session, limits_json=BURST)
    row = person(session, company(session, sid))
    other = person(session, company(session, sid), "박현장", OTHER_PHONE)
    for _ in range(3):
        rang(session, NOW, direction="out", origin="user")  # 우리가 건 통화
        rang(session, NOW, peer_number=OTHER_DIGITS)  # 다른 번호
        rang(session, NOW, peer_number=None, contact_id=other.id)  # 다른 연락처
        rang(session, NOW, peer_number=None)  # 번호 없는 전화
        texted(session, NOW, peer_number=OTHER_DIGITS)  # 다른 번호의 문자
    assert answer(session, "call") == ("engage", "known_caller")
    rang(session, NOW, peer_number=None, contact_id=row.id)  # 연락처에 걸린 줄과
    rang(session, NOW)  # 번호가 적힌 줄을 함께 센다
    assert answer(session, "call") == ("engage", "known_caller")
    rang(session, NOW, status="rejected")  # 거절한 줄도 한 번이다
    assert answer(session, "call") == ("reject", "burst_limit")
    assert answer(session, "sms", body="내일 가능합니다") == ("engage", "known_caller")  # 문자는 들어온 문자 줄을 센다


def test_the_row_of_this_call_is_not_counted_when_it_was_written_first(session, sid):
    """줄을 먼저 쓰고 판정을 묻는 쪽은 그 줄의 id 를 넘긴다(exclude_call_id) — 이번 것은 세지 않는다."""
    connect(session, limits_json={**BURST, "unknown_calls_hourly": 1})
    person(session, company(session, sid))
    for _ in range(2):
        rang(session, NOW)
    mine = rang(session, NOW, status="in_call")  # 이번 통화의 줄
    assert answer(session, "call") == ("reject", "burst_limit")  # 넘기지 않으면 이번 줄까지 센다
    assert answer(session, "call", exclude_call_id=mine.id) == ("engage", "known_caller")
    assert answer(session, "call", exclude_message_id=mine.id) == ("reject", "burst_limit")  # 문자 줄의 id 는 전화에 쓰지 않는다
    stranger = rang(session, NOW, peer_number=OTHER_DIGITS, caller_class="unknown", status="in_call")
    assert answer(session, "call", OTHER_PHONE) == ("reject", "burst_limit")  # 모르는 번호 전체 상한(1)에 자기 줄이 닿는다
    assert answer(session, "call", OTHER_PHONE, exclude_call_id=stranger.id) == ("engage", "unknown_accepted")


def test_calls_without_a_number_are_one_bundle(session, sid):
    connect(session, limits_json=BURST)
    row = person(session, company(session, sid))
    for _ in range(2):
        rang(session, NOW, peer_number=None, caller_class="withheld")
    rang(session, NOW, peer_number=None, contact_id=row.id)  # 연락처에 걸린 줄(번호 칸이 비어도)은 묶음이 아니다
    assert answer(session, "call", None) == ("engage", "unknown_accepted")
    rang(session, NOW, peer_number=phone.NO_NUMBER, caller_class="withheld")  # 번호 칸에 무엇이 적혔든 등급으로 센다
    for number in (None, phone.NO_NUMBER, "anonymous"):
        assert answer(session, "call", number) == ("reject", "burst_limit")
    assert answer(session, "call", OTHER_PHONE) == ("engage", "unknown_accepted")  # 번호 있는 전화는 그 묶음이 아니다


def test_rows_with_neither_number_nor_contact_are_in_the_no_number_bundle(session):
    """등급이 withheld 로 적히지 않았어도(시험 모드 때 거절한 줄 등) 번호도 연락처도 없는 줄은 번호 없는 묶음이다."""
    connect(session, limits_json=BURST)
    for caller_class in (None, "outside_test", "withheld"):
        rang(session, NOW, peer_number=None, caller_class=caller_class, status="rejected")
    assert answer(session, "call", None) == ("reject", "burst_limit")
    assert answer(session, "call", OTHER_PHONE) == ("engage", "unknown_accepted")


def test_no_number_marker_is_never_a_burst_key_for_numbered_callers(session):
    connect(session, limits_json=BURST)
    for _ in range(3):
        rang(session, NOW, peer_number=phone.NO_NUMBER)
    assert answer(session, "call", OTHER_PHONE) == ("engage", "unknown_accepted")
    assert answer(session, "call", FOREIGN) == ("engage", "unknown_accepted")


def test_foreign_caller_bursts_on_its_own_key(session):
    connect(session, limits_json=BURST)
    for _ in range(3):
        rang(session, NOW, peer_number="15880199")  # 국내 대표번호의 줄
    assert answer(session, "call", "+15880199") == ("engage", "unknown_accepted")
    for _ in range(3):
        rang(session, NOW, peer_number=door.stored_peer_number("+1 588 0199"))
    assert answer(session, "call", "+15880199") == ("reject", "burst_limit")
    assert answer(session, "call", REP_PHONE) == ("reject", "burst_limit")


def test_texts_burst_on_what_came_in(session, sid):
    """문자도 전화처럼 **들어온 줄**을 센다 — 답이 초안으로만 남아도(승인 받기) 폭주가 멈춘다."""
    conn = connect(session, limits_json={**BURST, "auto_reply_hourly": 99, "auto_reply_daily": 99})  # 5분에 3번
    row = person(session, company(session, sid))
    texted(session, NOW - timedelta(minutes=5))  # 꼭 5분 전의 줄까지 센다
    texted(session, NOW - timedelta(minutes=1), peer_number=None, contact_id=row.id)  # 연락처에 걸린 줄
    for _ in range(3):
        texted(session, NOW, peer_number=OTHER_DIGITS)  # 다른 번호의 문자
        texted(session, NOW, direction="out", origin="user", status="accepted")  # 우리가 보낸 문자
        rang(session, NOW)  # 그 번호의 전화
    assert answer(session, "sms", body="네") == ("engage", "known_caller")  # 두 번 — 문턱 아래
    mine = texted(session, NOW)
    assert answer(session, "sms", body="네") == ("record", "burst_limit")  # 세 번
    assert answer(session, "sms", body="네", exclude_message_id=mine.id) == ("engage", "known_caller")  # 이번 줄은 빼고
    assert answer(session, "sms", body="네", exclude_call_id=mine.id) == ("record", "burst_limit")  # 통화 줄 id 는 문자에 안 쓴다
    assert answer(session, "sms", body="네", now=NOW + timedelta(seconds=1)) == ("engage", "known_caller")  # 5분 넘긴 줄은 뺀다
    assert answer(session, "call") == ("reject", "burst_limit")  # 전화는 전화 줄을 센다(세 번)
    set_limits(session, conn, inbound_burst_count=4)  # 설정을 바꾸면 다음 판정부터
    assert answer(session, "sms", body="네") == ("engage", "known_caller")


@pytest.mark.parametrize("number,expected", [(SENTINEL_PHONE, ("engage", "known_caller")),
                                             (OTHER_PHONE, ("notice", "unknown_accepted"))])
def test_a_flood_of_texts_is_capped_even_when_replies_stay_drafts(session, sid, number, expected):
    """리뷰 I-2: 승인 받기에서는 답이 초안이라 차지되지 않는다 — 1초에 한 통씩 60통이 와도 응대는 몇 번뿐이다."""
    connect(session, limits_json={"inbound_burst_count": 5, "inbound_burst_minutes": 10, "auto_reply_hourly": 3,
                                  "auto_reply_daily": 20, "unknown_notice_daily": 2, "unknown_notice_total_daily": 9})
    row = person(session, company(session, sid))
    digits, verdicts = phone.normalize(number), []
    for second in range(60):
        at = NOW + timedelta(seconds=second)
        mine = texted(session, at, peer_number=digits, contact_id=None)  # 받은 쪽은 줄을 먼저 쓴다
        admitted = admit(session, "sms", number, now=at, body=f"문자 {second}", exclude_message_id=mine.id)
        verdicts.append((admitted.verdict, admitted.reason))
        if admitted.verdict in ("engage", "notice"):  # 답·안내는 초안으로만 남는다
            replied(session, at, claimed=False, peer_number=None if number == SENTINEL_PHONE else digits,
                    contact_id=row.id if number == SENTINEL_PHONE else None,
                    kind="auto_reply" if admitted.verdict == "engage" else "notice")
    taken = 3 if number == SENTINEL_PHONE else 2  # 연락처: 한 시간 자동 답 3 · 모르는 번호: 하루 안내 2
    assert verdicts[:taken] == [expected] * taken
    assert verdicts[taken:5] == [("record", "auto_reply_limit")] * (5 - taken)
    assert verdicts[5:] == [("record", "burst_limit")] * 55  # 여섯 번째부터는 잦은 문자


# ── 5 자동 답 상한: 만든 것을 센다 ──────────────────────────────────


def test_auto_reply_cap_counts_replies_made_for_that_number(session, sid):
    connect(session, limits_json={**REPLIES, "inbound_burst_count": 99})  # 한 시간 2번 · 하루 3번
    row = person(session, company(session, sid))
    replied(session, NOW - timedelta(minutes=59), peer_number=None, contact_id=row.id)  # 연락처에 걸린 줄
    replied(session, NOW, peer_number=OTHER_DIGITS)  # 다른 번호 앞으로 만든 답
    replied(session, NOW, kind="normal")  # 사람이 보낸 보통 문자
    replied(session, NOW, kind="dnc_confirm")  # 수신 거부 확인 문자
    texted(session, NOW, kind="auto_reply")  # 들어온 줄(종류 칸에 무엇이 있든)
    assert answer(session, "sms", body="내일 가능합니다") == ("engage", "known_caller")
    replied(session, NOW - timedelta(minutes=60), claimed=False)  # 나가지 않은 초안도 만든 것이다 · 꼭 한 시간 전까지 센다
    assert answer(session, "sms", body="내일 가능합니다") == ("record", "auto_reply_limit")
    assert answer(session, "sms", body="내일 가능합니다", now=NOW + timedelta(seconds=1)) == ("engage", "known_caller")
    assert answer(session, "call") == ("engage", "known_caller")  # 전화에는 자동 답 상한을 쓰지 않는다


def test_auto_reply_cap_counts_notices_too(session):
    connect(session, limits_json={**REPLIES, "unknown_notice_daily": 9, "unknown_notice_total_daily": 9})
    replied(session, NOW, kind="notice", peer_number=OTHER_DIGITS, claimed=False)
    assert answer(session, "sms", OTHER_PHONE, body="일정 알려 주세요") == ("notice", "unknown_accepted")
    replied(session, NOW, kind="notice", peer_number=OTHER_DIGITS)
    assert answer(session, "sms", OTHER_PHONE, body="일정 알려 주세요") == ("record", "auto_reply_limit")


def test_auto_reply_daily_cap_counts_the_seoul_day(session, sid):
    conn = connect(session, limits_json={**REPLIES, "inbound_burst_count": 99})
    row = person(session, company(session, sid))
    early = datetime(2026, 11, 24, 0, 30, tzinfo=KST)
    for hour in (1, 3):
        replied(session, early + timedelta(hours=hour), peer_number=None, contact_id=row.id, claimed=hour == 1)
    replied(session, early - timedelta(minutes=40))  # 어제 23:50 — 한 시간 안이지만 오늘 것은 아니다
    noon = datetime(2026, 11, 24, 12, 0, tzinfo=KST)
    assert answer(session, "sms", body="네", now=noon) == ("engage", "known_caller")  # 오늘 2번
    replied(session, early + timedelta(hours=5), claimed=False)
    assert answer(session, "sms", body="네", now=noon) == ("record", "auto_reply_limit")  # 오늘 3번
    assert answer(session, "sms", body="네", now=noon + timedelta(days=1)) == ("engage", "known_caller")
    set_limits(session, conn, auto_reply_daily=4)
    assert answer(session, "sms", body="네", now=noon) == ("engage", "known_caller")
    set_limits(session, conn, auto_reply_hourly=0, auto_reply_daily=0)  # 0 = 자동 답을 하지 않는다
    assert answer(session, "sms", body="네", now=noon + timedelta(days=1)) == ("record", "auto_reply_limit")


def test_hourly_cap_reaches_back_over_midnight(session, sid):
    connect(session, limits_json=REPLIES)
    person(session, company(session, sid))
    early = datetime(2026, 11, 24, 0, 30, tzinfo=KST)
    for minutes in (35, 45):  # 어제 23:55·23:45
        replied(session, early - timedelta(minutes=minutes))
    assert answer(session, "sms", body="네", now=early) == ("record", "auto_reply_limit")


def test_now_without_a_timezone_is_utc(session, monkeypatch):
    """시간대 없는 now 는 UTC 다(DB 와 같은 규칙) — 서버의 시간대에 따라 「오늘」이 달라지지 않는다."""
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        connect(session, limits_json={**ROOMY, "unknown_notice_daily": 1})
        aware = datetime(2026, 11, 23, 21, 0, tzinfo=KST)  # 서울 23일 21:00 = UTC 12:00
        naive = datetime(2026, 11, 23, 12, 0)
        replied(session, aware - timedelta(hours=1), kind="notice", peer_number=OTHER_DIGITS)  # 서울 오늘 20:00 의 안내
        for now in (aware, naive):
            assert answer(session, "sms", OTHER_PHONE, body="일정 알려 주세요", now=now) == ("record", "auto_reply_limit")
            assert answer(session, "call", OTHER_PHONE, now=now) == ("engage", "unknown_accepted")
        day_later = naive + timedelta(hours=3)  # UTC 15:00 = 서울 24일 00:00 — 날이 바뀌었다
        assert answer(session, "sms", OTHER_PHONE, body="일정 알려 주세요", now=day_later) == ("notice", "unknown_accepted")
    finally:
        monkeypatch.undo()
        time.tzset()


# ── 2 수신 거부 말 ──────────────────────────────────────────────────


@pytest.mark.parametrize("body", [
    "수신거부", "수신 거부", "  수신거부  ", "수신  거부", "수신거부.", "[수신거부]", "'수신거부'", "수신\u200b거부",
    "수신거부요", "수신거부 합니다", "수신 거부 부탁드립니다", "수신거부 해주세요", "수신거부 해 주세요.", "수신거부입니다",
    "수신거부 하겠습니다", "수신거부 할게요", "수신 거부 신청합니다", "[Web발신]\n수신거부",
    "그만", "그만!", "그만~", " 그 만 ", "stop", "STOP", "Stop.", "STOP!!", "ＳＴＯＰ", "s t o p",
])
def test_stop_words(session, sid, body):
    connect(session)
    person(session, company(session, sid))
    assert answer(session, "sms", body=body) == ("stop", "stop_word")


@pytest.mark.parametrize("body", [
    "그만 철수합니다", "그만 하고 내일 다시 하겠습니다", "그만 마무리했습니다", "그만 보내세요", "그만요", "그만해주세요",
    "그만큼 진행했습니다", "그만둔 작업자 대신 두 명이 갑니다", "오늘은 이만하고 그만 하겠습니다",
    "stop work 지시 받았습니다", "Stop sign 설치 완료", "stop please", "stopper 교체했습니다", "non-stop 으로 타설합니다",
    "수신거부 아닙니다", "수신거부 아니에요", "수신거부 안 합니다", "수신 거부 한 적 없습니다", "수신거부는 아니고 내일 다시 주세요",
    "수신거부 했는데 왜 또 오나요", "문자 수신거부", "수신차단", "거부", "", None, "내일 가능합니다",
    "네 수신거부 아닙니다", "네, 수신거부요?",
])  # 「네 수신거부」는 H1 판정(11-24)으로 수신 거부가 되었다 — 대답 말 하나 뒤의 「수신거부」(test_call_safety)
def test_words_that_only_look_like_a_stop_are_not_a_stop(session, sid, body):
    """리뷰 M-1: 「그만」「stop」은 글 전체일 때만, 「수신거부」는 글 전체이거나 공손한 맺음말만 붙었을 때만 수신 거부다."""
    connect(session)
    person(session, company(session, sid))
    assert answer(session, "sms", body=body) == ("engage", "known_caller")


def test_stop_word_works_for_every_class_that_reaches_it(session, sid):
    connect(session, inbound_mode="known")
    person(session, company(session, sid))
    account(session, "user", "010-0000-0007")
    store.mark_do_not_contact(session, "010-0000-0008", reason="그만")
    for number in (SENTINEL_PHONE, OTHER_PHONE, "010-0000-0007", "010-0000-0008", REP_PHONE):  # 연락처·모르는 번호·내부·수신 거부·대표번호
        assert answer(session, "sms", number, body="수신거부", has_media=True) == ("stop", "stop_word")
    assert answer(session, "call", body="수신거부") == ("engage", "known_caller")  # 전화에는 글이 없다


def test_stop_word_is_heard_when_nothing_else_is_taken(session, sid):
    """리뷰 I-3: 받지 않음(기본값)·잦은 문자·자동 답 상한(0 포함)에서도 수신 거부 말은 먹히지 않는다."""
    conn = connect(session, inbound_mode="off", limits_json={**BURST, "auto_reply_hourly": 0, "auto_reply_daily": 0})
    person(session, company(session, sid))
    for _ in range(5):
        texted(session, NOW)
        replied(session, NOW)
    for mode in ("off", "known", "all", "everything"):
        conn.inbound_mode = mode
        session.flush()
        for number in (SENTINEL_PHONE, OTHER_PHONE):
            assert answer(session, "sms", number, body="수신거부") == ("stop", "stop_word")
    assert answer(session, "sms", body="네") == ("record", "inbound_off")  # 다른 글은 그대로 표를 따른다


def test_stop_from_a_number_outside_the_address_book_asks_for_no_confirmation_text(session, sid):
    """리뷰 I-5: 주소록에 없는 번호의 수신 거부 말 — 번호는 표시하되(stop) 모르는 사람에게 확인 문자를 보내지 않는다."""
    connect(session)
    person(session, company(session, sid))
    person(session, company(session, sid, "숨김사"), "숨은이", "010-0000-0011", hidden=True)
    account(session, "user", "010-0000-0007")
    store.mark_do_not_contact(session, "010-0000-0008", reason="그만")
    for number, confirm in ((SENTINEL_PHONE, True), ("010-0000-0007", True), (OTHER_PHONE, False),
                            ("010-0000-0008", False), ("010-0000-0011", False), (REP_PHONE, False)):
        admitted = admit(session, "sms", number, body="수신거부")
        assert (admitted.verdict, admitted.confirm) == ("stop", confirm)
    assert admit(session, "sms", body="내일 가능합니다").confirm is False  # 수신 거부 말이 아니면 늘 거짓
    assert admit(session, "call").confirm is False


@pytest.mark.parametrize("number", [None, phone.NO_NUMBER, FOREIGN])
def test_stop_word_needs_a_number_that_can_be_marked(session, number):
    """표시할 국내 번호가 없으면 수신 거부로 넘기지 않는다(번호 없음·나라 밖 번호는 기록만)."""
    conn = connect(session)
    assert answer(session, "sms", number, body="수신거부") == ("record", "machine_text")
    conn.inbound_mode = "off"
    session.flush()
    assert answer(session, "sms", number, body="수신거부") == ("record", "inbound_off")


# ── 6 기계 문자 · 7 사진 ────────────────────────────────────────────

CLEARLY_MACHINE = [  # 누가 보냈든 기계가 보낸 글: 맨 앞의 (광고) 표지, 인증번호와 4~8자리 숫자뿐인 글
    "(광고) 자재 특가 안내", "（광고）자재 특가", "(광 고) 특가", "[Web발신] (광고) 특가 안내\n무료수신거부 080-000-0199",
    "[Web발신] 인증번호 [0000] 를 입력해 주세요", "인증번호는 0000 입니다", "인증 번호 0000", "[국제발신]\n인증번호 000000",
    "본인확인 인증번호[000000]", "인증코드 00000000", "Your verification code is 000000", "OTP 0000",
]
MACHINE_FROM_A_STRANGER = [  # 주소록에 없는 번호가 보냈을 때만 기계 글로 본다(연락처가 보냈으면 사람의 글)
    "[web발신] 안내드립니다", "[WEB발신]\n택배가 도착했습니다", "[국제발신] hello", "인증번호 받으셨나요?",
    "자재 특가 안내 무료수신거부 080-000-0199", "특가 안내\n무료 수신거부 0800000199", "광고 아닙니다 (광고) 라고 붙이지 마세요",
    "인증번호 0000 받았는데 내일 9시에 타설합니다", "[Web발신]\n내일 타설 가능합니다 - 가나건설",
    "verification code: 000000 do not share", "Use OTP 000000 to sign in", "http://example.invalid/x",
    "https://example.invalid/a www.example.invalid/b", "[Web발신] https://example.invalid/x",
]
FROM_A_PERSON = [  # 누가 보냈든 사람의 글
    "내일 방문해도 될까요?", "자세한 건 http://example.invalid/x 참고하세요", "광고 문의드립니다", "hotpot 예약했습니다",
    "인증 받았습니다 번호는 내일 드릴게요", "",
]


@pytest.mark.parametrize("body", CLEARLY_MACHINE)
def test_clearly_machine_text_gets_no_reply_whoever_sent_it(session, sid, body):
    connect(session)
    person(session, company(session, sid))
    account(session, "user", "010-0000-0007")
    for number in (SENTINEL_PHONE, OTHER_PHONE, "010-0000-0007"):  # 주소록·계정에 있는 번호로 와도 답하지 않는다
        assert answer(session, "sms", number, body=body) == ("record", "machine_text")


@pytest.mark.parametrize("body", MACHINE_FROM_A_STRANGER)
def test_machine_marks_do_not_silence_a_contact(session, sid, body):
    """리뷰 M-2: 연락처가 「인증번호」를 말하거나 글이 [Web발신] 으로 시작한다고 조용히 기록만 하지 않는다."""
    connect(session)
    person(session, company(session, sid))
    account(session, "user", "010-0000-0007")
    assert answer(session, "sms", body=body) == ("engage", "known_caller")
    assert answer(session, "sms", "010-0000-0007", body=body) == ("engage", "known_caller")
    assert answer(session, "sms", OTHER_PHONE, body=body) == ("record", "machine_text")  # 모르는 번호는 그대로 기계 글


@pytest.mark.parametrize("body", FROM_A_PERSON)
def test_a_persons_text_is_not_machine_text(session, sid, body):
    connect(session)
    person(session, company(session, sid))
    assert answer(session, "sms", body=body) == ("engage", "known_caller")
    assert answer(session, "sms", OTHER_PHONE, body=body) == ("notice", "unknown_accepted")


@pytest.mark.parametrize("number", [REP_PHONE, LANDLINE, "0507-1234-0199", "080-000-0199", "1234", "#0199", FOREIGN,
                                    None, phone.NO_NUMBER])
def test_text_from_a_non_mobile_number_outside_the_address_book_is_machine_text(session, number):
    connect(session)
    assert answer(session, "sms", number, body="내일 오전에 방문드리겠습니다") == ("record", "machine_text")


def test_non_mobile_number_in_the_address_book_or_of_an_account_is_not_machine_text(session, sid):
    connect(session)
    person(session, company(session, sid), number=REP_PHONE)
    account(session, "user", LANDLINE)
    assert answer(session, "sms", REP_PHONE, body="내일 가능합니다") == ("engage", "known_caller")
    assert answer(session, "sms", LANDLINE, body="내일 가능합니다") == ("engage", "known_caller")


def test_hidden_contacts_non_mobile_number_is_outside_the_address_book(session, sid):
    connect(session)
    person(session, company(session, sid), number=REP_PHONE, hidden=True)
    assert answer(session, "sms", REP_PHONE, body="내일 가능합니다") == ("record", "machine_text")


def test_photo_message_is_record_only(session, sid):
    connect(session)
    person(session, company(session, sid))
    for number in (SENTINEL_PHONE, OTHER_PHONE):
        assert answer(session, "sms", number, body="사진 보냅니다", has_media=True) == ("record", "media_attached")
    assert answer(session, "sms", body="(광고) 사진", has_media=True) == ("record", "machine_text")
    assert answer(session, "call", has_media=True) == ("engage", "known_caller")  # 전화에는 없는 것


# ── 8 수신 거부 번호 ────────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["known", "all"])
def test_dnc_contact_call_engages_sms_records(session, sid, mode):
    connect(session, inbound_mode=mode)
    person(session, company(session, sid), do_not_contact=True)  # 보이는 연락처의 번호
    admitted = admit(session, "call")
    assert (admitted.verdict, admitted.reason) == ("engage", "do_not_contact")  # 메모만 — 도구는 등급이 정한다
    assert admitted.caller.caller_class == "do_not_contact" and admitted.caller.candidates
    assert answer(session, "sms", body="내일 가능합니다") == ("record", "do_not_contact")


@pytest.mark.parametrize("who", ["number_only", "hidden_contact", "wrong_number_contact"])
def test_dnc_number_without_a_visible_contact_follows_the_inbound_mode(session, sid, who):
    """리뷰 I-1: 모르는 번호가 「수신거부」를 보내 표시된 뒤 「아는 번호만」에서 전화가 받아지면 안 된다 — 보이는 연락처가 없는
    수신 거부 번호의 전화는 모르는 번호처럼 받는 범위를 따른다(등급은 do_not_contact, 범위는 없음 그대로)."""
    conn = connect(session, inbound_mode="known", limits_json={"unknown_calls_hourly": 1})
    if who == "number_only":
        store.mark_do_not_contact(session, SENTINEL_PHONE, reason="전화하지 마세요")
    else:
        person(session, company(session, sid), do_not_contact=True, hidden=who == "hidden_contact",
               phone_invalid=who == "wrong_number_contact")
    admitted = admit(session, "call")
    assert (admitted.verdict, admitted.reason) == ("reject", "unknown_not_accepted")
    assert admitted.caller == Caller("do_not_contact", (), None)
    assert door.scope_of(session, admitted.caller).facts == "none"
    assert answer(session, "sms", body="내일 가능합니다") == ("record", "do_not_contact")
    conn.inbound_mode = "all"
    session.flush()
    assert answer(session, "call") == ("engage", "unknown_accepted")  # 「모두」에서는 모르는 번호의 길로
    assert answer(session, "call", live_calls=door.MAX_LIVE_CALLS) == ("missed", "line_busy")
    assert answer(session, "sms", body="내일 가능합니다") == ("record", "do_not_contact")  # 안내도 보내지 않는다
    rang(session, NOW, peer_number=OTHER_DIGITS, caller_class="unknown")  # 모르는 번호 전체 상한(1)도 같이 따른다
    assert answer(session, "call") == ("reject", "burst_limit")


# ── 9 모르는 번호 · 번호 표시 제한 ──────────────────────────────────


def test_known_mode_keeps_unknown_out(session, sid):
    connect(session, inbound_mode="known")
    person(session, company(session, sid))
    for number in (OTHER_PHONE, None, FOREIGN, REP_PHONE):
        assert answer(session, "call", number) == ("reject", "unknown_not_accepted")
    assert answer(session, "sms", OTHER_PHONE, body="일정 알려 주세요") == ("record", "unknown_not_accepted")
    assert answer(session, "call") == ("engage", "known_caller")
    assert answer(session, "sms", body="일정 알려 주세요") == ("engage", "known_caller")


def test_all_mode_unknown_call_engages_sms_gets_notice(session):
    connect(session, inbound_mode="all", limits_json={"unknown_notice_daily": 1})
    for number in (OTHER_PHONE, None, FOREIGN):
        admitted = admit(session, "call", number)
        assert (admitted.verdict, admitted.reason) == ("engage", "unknown_accepted")
        assert admitted.caller.caller_class in ("unknown", "withheld")
    assert answer(session, "sms", OTHER_PHONE, body="일정 알려 주세요") == ("notice", "unknown_accepted")


def test_unknown_notice_stops_at_its_daily_limit(session):
    conn = connect(session, limits_json={**ROOMY, "unknown_notice_daily": 1})
    replied(session, NOW - timedelta(days=1), kind="notice", peer_number=OTHER_DIGITS)  # 어제의 안내
    replied(session, NOW, kind="auto_reply", peer_number=OTHER_DIGITS)  # 안내가 아닌 자동 답
    assert answer(session, "sms", OTHER_PHONE, body="일정 알려 주세요") == ("notice", "unknown_accepted")
    replied(session, NOW - timedelta(hours=3), kind="notice", peer_number=OTHER_DIGITS, claimed=False)  # 초안도 만든 것
    assert answer(session, "sms", OTHER_PHONE, body="일정 알려 주세요") == ("record", "auto_reply_limit")
    assert answer(session, "sms", "010-0000-0009", body="일정 알려 주세요") == ("notice", "unknown_accepted")
    set_limits(session, conn, unknown_notice_daily=2)
    assert answer(session, "sms", OTHER_PHONE, body="일정 알려 주세요") == ("notice", "unknown_accepted")
    set_limits(session, conn, unknown_notice_daily=0)
    assert answer(session, "sms", "010-0000-0009", body="일정 알려 주세요") == ("record", "auto_reply_limit")


def test_notices_to_all_unknown_numbers_share_one_daily_total(session, sid):
    """리뷰 I-5: 번호를 바꿔 가며 보내도 고정 안내는 하루 전체 상한(unknown_notice_total_daily)까지만 만든다."""
    conn = connect(session, limits_json={**ROOMY, "unknown_notice_total_daily": 2})
    person(session, company(session, sid))
    replied(session, NOW - timedelta(days=1), kind="notice", peer_number="01000000011")  # 어제의 안내
    replied(session, NOW, kind="auto_reply", peer_number=None, contact_id=1)  # 연락처에게 간 자동 답은 안내가 아니다
    replied(session, NOW, kind="notice", peer_number="01000000012", claimed=False)  # 초안도 만든 것
    assert answer(session, "sms", OTHER_PHONE, body="일정 알려 주세요") == ("notice", "unknown_accepted")
    replied(session, NOW - timedelta(hours=9), kind="notice", peer_number="01000000013")  # 서울 오늘 01:00
    assert answer(session, "sms", OTHER_PHONE, body="일정 알려 주세요") == ("record", "auto_reply_limit")
    assert answer(session, "sms", body="일정 알려 주세요") == ("engage", "known_caller")  # 연락처에는 쓰지 않는다
    assert answer(session, "sms", OTHER_PHONE, body="일정 알려 주세요",
                  now=NOW + timedelta(days=1)) == ("notice", "unknown_accepted")
    set_limits(session, conn, unknown_notice_total_daily=3)
    assert answer(session, "sms", OTHER_PHONE, body="일정 알려 주세요") == ("notice", "unknown_accepted")
    set_limits(session, conn, unknown_notice_total_daily=0)  # 0 = 안내를 만들지 않는다
    assert answer(session, "sms", OTHER_PHONE, body="일정 알려 주세요",
                  now=NOW + timedelta(days=1)) == ("record", "auto_reply_limit")


def test_unknown_callers_share_one_hourly_total(session, sid):
    """리뷰 I-4: 모르는 번호·번호 숨김 전화는 모두 합쳐 한 시간에 unknown_calls_hourly 통까지만 응대한다."""
    conn = connect(session, limits_json={**ROOMY, "unknown_calls_hourly": 2})
    row = person(session, company(session, sid))
    rang(session, NOW - timedelta(minutes=60), peer_number="01000000011", caller_class="unknown")  # 꼭 60분 전까지 센다
    rang(session, NOW, peer_number="01000000012", caller_class="unknown", status="rejected")  # 거절한 줄
    rang(session, NOW, peer_number="01000000013", caller_class="unknown", status="missed")  # 받지 못한 줄
    rang(session, NOW, peer_number=None, contact_id=row.id, caller_class="contact")  # 연락처의 통화
    rang(session, NOW, peer_number="01000000014", caller_class="unknown", direction="out", origin="user")  # 우리가 건 통화
    for number in (OTHER_PHONE, None, FOREIGN):
        assert answer(session, "call", number) == ("engage", "unknown_accepted")  # 응대한 것은 하나뿐
    rang(session, NOW, peer_number=None, caller_class="withheld", status="in_call")  # 번호 숨김도 같이 센다
    for number in (OTHER_PHONE, None, FOREIGN, "010-0000-0015"):
        assert answer(session, "call", number) == ("reject", "burst_limit")
    assert answer(session, "call") == ("engage", "known_caller")  # 연락처는 이 상한과 상관없다
    assert answer(session, "sms", OTHER_PHONE, body="일정 알려 주세요") == ("notice", "unknown_accepted")  # 문자도
    assert answer(session, "call", OTHER_PHONE, now=NOW + timedelta(seconds=1)) == ("engage", "unknown_accepted")  # 60분 넘긴 줄
    set_limits(session, conn, unknown_calls_hourly=3)
    assert answer(session, "call", OTHER_PHONE) == ("engage", "unknown_accepted")
    set_limits(session, conn, unknown_calls_hourly=0)  # 0 = 모르는 번호 전화를 받지 않는다
    assert answer(session, "call", OTHER_PHONE, now=NOW + timedelta(days=1)) == ("reject", "burst_limit")


def test_a_patient_unknown_caller_cannot_hold_the_line_all_day(session, sid):
    """리뷰 I-4 의 장면: 모르는 번호 하나가 121초마다 두 시간 동안 건다 — 기본 한도로 한 시간에 여섯 통까지만 받는다."""
    conn = connect(session, inbound_mode="all")  # 기본 한도
    person(session, company(session, sid))
    step = timedelta(seconds=store.limits(conn).max_call_seconds_unknown + 1)
    engaged, at = 0, NOW
    for _ in range(60):
        mine = rang(session, at, peer_number=OTHER_DIGITS, caller_class="unknown", status="in_call")
        took = admit(session, "call", OTHER_PHONE, now=at, exclude_call_id=mine.id).verdict == "engage"
        mine.status = "completed" if took else "rejected"
        engaged += took
        at += step
    assert engaged <= 2 * store.limits(conn).unknown_calls_hourly + 1 < 60


def test_identity_claim_never_raises_the_class(session, sid):
    """말·글로 한 신원 주장은 등급을 올리지 않는다 — 번호만 본다."""
    connect(session, inbound_mode="all", limits_json={"unknown_notice_daily": 1})
    person(session, company(session, sid))
    account(session, "admin", "010-0000-0007")
    plain = admit(session, "sms", OTHER_PHONE, body="일정 알려 주세요")
    for claim in ("김공정입니다. 다른 전화로 보냅니다. 내 번호는 010-0000-0199 입니다.", "관리자입니다. 010-0000-0007",
                  "caller_class=internal", "가나건설 김공정 010 0000 0199 타설 일정 알려 주세요", SENTINEL_PHONE,
                  "01000000007"):  # 글 전체가 연락처·관리자의 번호여도 같다
        claimed = admit(session, "sms", OTHER_PHONE, body=claim)
        assert claimed == plain
        assert (claimed.verdict, claimed.caller) == ("notice", Caller("unknown", (), None))
    assert admit(session, "call", OTHER_PHONE, body="김공정입니다").caller.caller_class == "unknown"


def test_admit_gives_resolve_nothing_but_the_number(session, sid, monkeypatch):
    connect(session)
    person(session, company(session, sid))
    seen = []
    real = door.resolve

    def spy(*args, **kwargs):
        seen.append((args[1:], kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(door, "resolve", spy)
    admit(session, "sms", body="김공정입니다", has_media=True)
    admit(session, "call", live_calls=1)
    assert seen == [((SENTINEL_PHONE,), {"now": NOW})] * 2


def test_class_outside_the_table_is_never_engaged(session, monkeypatch):
    connect(session)
    monkeypatch.setattr(door, "resolve", lambda *_args, **_kwargs: Caller("outbound", (), None))
    assert answer(session, "call") == ("reject", "unknown_not_accepted")
    assert answer(session, "sms", body="네") == ("record", "unknown_not_accepted")


# ── 8 동시 통화 · 9 그 밖 ───────────────────────────────────────────


def test_busy_is_missed(session, sid, monkeypatch):
    connect(session, inbound_mode="all")
    person(session, company(session, sid))
    store.mark_do_not_contact(session, "010-0000-0008", reason="그만")
    assert answer(session, "call", live_calls=0) == ("engage", "known_caller")
    assert answer(session, "call", live_calls=door.MAX_LIVE_CALLS) == ("missed", "line_busy")
    assert answer(session, "call", OTHER_PHONE, live_calls=door.MAX_LIVE_CALLS) == ("missed", "line_busy")
    assert answer(session, "call", "010-0000-0008", live_calls=door.MAX_LIVE_CALLS + 1) == ("missed", "line_busy")
    assert answer(session, "sms", body="네", live_calls=door.MAX_LIVE_CALLS) == ("engage", "known_caller")
    monkeypatch.setattr(door, "MAX_LIVE_CALLS", 3)
    assert answer(session, "call", live_calls=2) == ("engage", "known_caller")
    assert answer(session, "call", live_calls=3) == ("missed", "line_busy")


def test_calls_we_would_not_take_are_rejected_not_missed(session, sid):
    connect(session, inbound_mode="known", limits_json=BURST)
    person(session, company(session, sid))
    block(session, "01000000004")
    busy = door.MAX_LIVE_CALLS
    assert answer(session, "call", OTHER_PHONE, live_calls=busy) == ("reject", "unknown_not_accepted")
    assert answer(session, "call", "010-0000-0004", live_calls=busy) == ("reject", "blocked_number")
    for _ in range(3):
        rang(session, NOW)
    assert answer(session, "call", live_calls=busy) == ("reject", "burst_limit")


@pytest.mark.parametrize("cls", ["internal", "contact", "contact_multi", "shared"])
@pytest.mark.parametrize("mode", ["known", "all"])
def test_known_classes_are_engaged_on_both_media(session, sid, cls, mode):
    connect(session, inbound_mode=mode)
    if cls == "internal":
        account(session, "user")
    else:
        firm = company(session, sid)
        person(session, firm)
        if cls == "contact_multi":
            person(session, company(session, second_schedule(session)))
        if cls == "shared":
            person(session, firm, "박현장")
    for medium in ("call", "sms"):
        admitted = admit(session, medium, body="내일 가능합니다")
        assert (admitted.verdict, admitted.reason, admitted.caller.caller_class) == ("engage", "known_caller", cls)


@pytest.mark.parametrize("medium", ["call", "sms"])
def test_internal_account_with_no_schedule_is_still_admitted_as_internal(session, medium):
    """볼 일정이 하나도 없는 내부 계정: 닫히는 것은 범위뿐이다 — 받기 판정(사건 `admission` 에 실릴 것)과 Caller 는 internal."""
    connect(session, inbound_mode="known")
    user = account(session, "user")
    admitted = admit(session, medium, body="내일 일정 알려 주세요")
    assert (admitted.verdict, admitted.reason) == ("engage", "known_caller")
    assert admitted.caller == Caller("internal", (), user.id)
    scope = door.scope_of(session, admitted.caller)
    assert (scope.schedule_ids, scope.candidates, scope.facts, scope.personal) == ((), (), "none", False)
    assert admitted.caller.caller_class == "internal"  # 범위를 만든 뒤에도 Caller 는 그대로다


# ── 코드만 판정한다 ─────────────────────────────────────────────────


def _door_tree() -> ast.Module:
    return ast.parse(inspect.getsource(door))


def test_door_has_no_limit_numbers_of_its_own():
    """문턱 숫자는 store.outreach.limits 에서만 온다 — 문에 상한 숫자 상수가 없다."""
    numbers = {node.value for node in ast.walk(_door_tree())
               if isinstance(node, ast.Constant) and type(node.value) in (int, float)}
    assert numbers <= {0, 1}


def test_door_asks_no_model_and_writes_no_log():
    """수신 거부 말·기계 문자·등급은 코드만 판정한다: 모델·네트워크·로그를 부르는 것을 들여오지 않는다."""
    imported = set()
    for node in ast.walk(_door_tree()):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    banned = ("app.llm", "app.agent", "app.outreach.provider", "app.outreach.harness.events", "httpx", "logging")
    assert not [name for name in imported if name.startswith(banned)]
