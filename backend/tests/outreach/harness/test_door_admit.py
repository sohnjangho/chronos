"""들어오는 문(Task 66) — 받기 판정표(door.admit): 전화와 문자가 같은 표를 같은 차례로 지난다. 번호는 모두 가상이다.

문턱 숫자는 시험마다 limits_json 에 명시해 넣는다(기본값에 기대지 않는다).
"""

import ast
import inspect
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


def replied(session: Session, at: datetime | None, **kw) -> OutreachMessage:
    """그 번호로 나간 자동 답 하나(at 이 None 이면 차지하지 않은 초안)."""
    row = OutreachMessage(**{"direction": "out", "channel": "sms", "origin": "agent", "kind": "auto_reply",
                             "body": "확인했습니다", "status": "accepted" if at else "draft", "claimed_at": at,
                             "peer_number": SENTINEL_DIGITS, **kw})
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
                    assert SENTINEL_DIGITS not in repr(admitted) and "0199" not in repr(admitted)
                    seen.add(admitted.reason)
    assert seen == set(ADMIT_REASONS)  # 판정표의 열세 코드가 모두 나온다


def test_admission_takes_only_the_shared_words():
    caller = Caller("unknown", (), None)
    assert door.ADMIT_VERDICTS == ("engage", "notice", "record", "reject", "missed", "stop")
    assert door.Admission("record", caller, "inbound_off").reason == "inbound_off"
    for verdict, reason in (("engage", "모르는 번호"), ("engage", "known"), ("answer", "known_caller"), ("", "")):
        with pytest.raises(ValueError):
            door.Admission(verdict, caller, reason)
    with pytest.raises(TypeError):
        door.Admission("engage", "contact", "known_caller")


def test_admit_takes_only_the_two_media(session):
    connect(session)
    for medium in ("kakao", "", None):
        with pytest.raises(ValueError):
            admit(session, medium)


# ── 1 받는 범위 「받지 않음」 ─────────────────────────────────────────


def test_mode_off(session, sid):
    connect(session, inbound_mode="off")
    account(session, "admin", OTHER_PHONE)
    person(session, company(session, sid))
    for number in (SENTINEL_PHONE, OTHER_PHONE, "010-0000-0009", None):
        assert answer(session, "call", number) == ("reject", "inbound_off")
        assert answer(session, "sms", number, body="수신거부") == ("record", "inbound_off")


def test_no_connection_or_an_unknown_mode_is_off(session, sid):
    person(session, company(session, sid))
    assert answer(session, "call") == ("reject", "inbound_off")
    assert answer(session, "sms", body="내일 가능합니다") == ("record", "inbound_off")
    connect(session, inbound_mode="everything")
    assert answer(session, "call") == ("reject", "inbound_off")
    assert answer(session, "sms", body="내일 가능합니다") == ("record", "inbound_off")


# ── 2 시험 모드 밖 · 차단 ────────────────────────────────────────────


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


# ── 3 되풀이 ────────────────────────────────────────────────────────


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
    assert answer(session, "call") == ("engage", "known_caller")
    rang(session, NOW, peer_number=None, contact_id=row.id)  # 연락처에 걸린 줄과
    rang(session, NOW)  # 번호가 적힌 줄을 함께 센다
    assert answer(session, "call") == ("engage", "known_caller")
    rang(session, NOW, status="rejected")  # 거절한 줄도 한 번이다
    assert answer(session, "call") == ("reject", "burst_limit")
    assert answer(session, "sms", body="내일 가능합니다") == ("engage", "known_caller")  # 문자에는 전화 문턱을 쓰지 않는다


def test_calls_without_a_number_are_one_bundle(session):
    connect(session, limits_json=BURST)
    for _ in range(2):
        rang(session, NOW, peer_number=None, caller_class="withheld")
    assert answer(session, "call", None) == ("engage", "unknown_accepted")
    rang(session, NOW, peer_number=phone.NO_NUMBER, caller_class="withheld")  # 번호 칸에 무엇이 적혔든 등급으로 센다
    for number in (None, phone.NO_NUMBER, "anonymous"):
        assert answer(session, "call", number) == ("reject", "burst_limit")
    assert answer(session, "call", OTHER_PHONE) == ("engage", "unknown_accepted")  # 번호 있는 전화는 그 묶음이 아니다


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
        rang(session, NOW, peer_number=door.number_key("+1 588 0199"))
    assert answer(session, "call", "+15880199") == ("reject", "burst_limit")
    assert answer(session, "call", REP_PHONE) == ("reject", "burst_limit")


def test_sms_flood_stops_at_auto_reply_cap(session, sid):
    connect(session, limits_json=REPLIES)  # 한 시간 2번 · 하루 3번
    person(session, company(session, sid))
    replied(session, NOW - timedelta(minutes=59))
    replied(session, None)  # 차지하지 않은 초안은 세지 않는다
    replied(session, NOW, peer_number=OTHER_DIGITS)  # 다른 번호로 나간 답
    replied(session, NOW, kind="normal")  # 사람이 보낸 보통 문자
    assert answer(session, "sms", body="내일 가능합니다") == ("engage", "known_caller")
    replied(session, NOW - timedelta(minutes=60))  # 꼭 한 시간 전까지 센다
    assert answer(session, "sms", body="내일 가능합니다") == ("record", "auto_reply_limit")
    assert answer(session, "sms", body="내일 가능합니다", now=NOW + timedelta(seconds=1)) == ("engage", "known_caller")
    assert answer(session, "call") == ("engage", "known_caller")  # 전화에는 자동 답 상한을 쓰지 않는다


def test_auto_reply_daily_cap_counts_the_seoul_day(session, sid):
    conn = connect(session, limits_json=REPLIES)
    row = person(session, company(session, sid))
    early = datetime(2026, 11, 24, 0, 30, tzinfo=KST)
    for hour in (1, 3):
        replied(session, early + timedelta(hours=hour), peer_number=None, contact_id=row.id)  # 연락처에 걸린 줄
    replied(session, early - timedelta(minutes=40))  # 어제 23:50 — 한 시간 안이지만 오늘 것은 아니다
    noon = datetime(2026, 11, 24, 12, 0, tzinfo=KST)
    assert answer(session, "sms", body="네", now=noon) == ("engage", "known_caller")  # 오늘 2번
    replied(session, early + timedelta(hours=5))
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


# ── 4 수신 거부 말 ──────────────────────────────────────────────────


@pytest.mark.parametrize("body", [
    "수신거부", "수신 거부", "  수신거부  ", "수신  거부", "수신거부.", "수신거부 해주세요", "수신 거부 부탁드립니다",
    "그만", "그만!", "그만 보내세요", "그만\n보내세요", "stop", "STOP", "Stop.", "stop please", "ＳＴＯＰ",
])
def test_stop_words(session, sid, body):
    connect(session)
    person(session, company(session, sid))
    assert answer(session, "sms", body=body) == ("stop", "stop_word")


@pytest.mark.parametrize("body", [
    "그만큼 진행했습니다", "그만둔 작업자 대신 두 명이 갑니다", "오늘은 이만하고 그만 하겠습니다", "문자 수신거부",
    "stopper 교체했습니다", "non-stop 으로 타설합니다", "수신거부는 아니고 내일 다시 주세요", "", None, "내일 가능합니다",
])
def test_stop_word_inside_other_words_or_sentences_is_not_a_stop(session, sid, body):
    connect(session)
    person(session, company(session, sid))
    assert answer(session, "sms", body=body) == ("engage", "known_caller")


def test_stop_word_works_for_every_class_that_reaches_it(session, sid):
    connect(session, inbound_mode="known")
    person(session, company(session, sid))
    account(session, "user", "010-0000-0007")
    store.mark_do_not_contact(session, "010-0000-0008", reason="그만")
    for number in (SENTINEL_PHONE, OTHER_PHONE, "010-0000-0007", "010-0000-0008"):  # 연락처·모르는 번호·내부·수신 거부
        assert answer(session, "sms", number, body="수신거부", has_media=True) == ("stop", "stop_word")
    assert answer(session, "call", body="수신거부") == ("engage", "known_caller")  # 전화에는 글이 없다


@pytest.mark.parametrize("number", [None, phone.NO_NUMBER, FOREIGN])
def test_stop_word_needs_a_number_that_can_be_marked(session, number):
    """표시할 국내 번호가 없으면 수신 거부로 넘기지 않는다(번호 없음·나라 밖 번호는 기록만)."""
    connect(session)
    assert answer(session, "sms", number, body="수신거부") == ("record", "machine_text")


# ── 5 기계 문자 · 사진 ──────────────────────────────────────────────


@pytest.mark.parametrize("body", [
    "[Web발신] 인증번호 [0000] 를 입력해 주세요", "인증번호는 0000 입니다", "인증 번호 0000", "(광고) 자재 특가 안내",
    "（광고）자재 특가", "(광 고) 특가", "[web발신] 안내드립니다", "[WEB발신]\n택배가 도착했습니다",
    "자재 특가 안내 무료수신거부 080-000-0199", "특가 안내\n무료 수신거부 0800000199",
])
def test_machine_text_gets_no_reply(session, sid, body):
    connect(session)
    person(session, company(session, sid))
    for number in (SENTINEL_PHONE, OTHER_PHONE):  # 주소록에 있는 번호로 와도 기계 글이면 답하지 않는다
        assert answer(session, "sms", number, body=body) == ("record", "machine_text")


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


# ── 6 수신 거부 번호 ────────────────────────────────────────────────


def test_dnc_number_call_engages_sms_records(session, sid):
    connect(session, inbound_mode="known")
    person(session, company(session, sid), do_not_contact=True)
    store.mark_do_not_contact(session, OTHER_PHONE, reason="전화하지 마세요")  # 주소록에 없는 수신 거부 번호
    for number in (SENTINEL_PHONE, OTHER_PHONE):
        admitted = admit(session, "call", number)
        assert (admitted.verdict, admitted.reason) == ("engage", "do_not_contact")  # 메모만 — 도구는 등급이 정한다
        assert admitted.caller.caller_class == "do_not_contact"
        assert answer(session, "sms", number, body="내일 가능합니다") == ("record", "do_not_contact")


# ── 7 모르는 번호 · 번호 표시 제한 ──────────────────────────────────


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
    conn = connect(session, limits_json={"unknown_notice_daily": 1, "auto_reply_hourly": 9, "auto_reply_daily": 9})
    replied(session, NOW - timedelta(days=1), kind="notice", peer_number=OTHER_DIGITS)  # 어제의 안내
    replied(session, NOW, kind="auto_reply", peer_number=OTHER_DIGITS)  # 안내가 아닌 자동 답
    assert answer(session, "sms", OTHER_PHONE, body="일정 알려 주세요") == ("notice", "unknown_accepted")
    replied(session, NOW - timedelta(hours=3), kind="notice", peer_number=OTHER_DIGITS)
    assert answer(session, "sms", OTHER_PHONE, body="일정 알려 주세요") == ("record", "auto_reply_limit")
    assert answer(session, "sms", "010-0000-0009", body="일정 알려 주세요") == ("notice", "unknown_accepted")
    set_limits(session, conn, unknown_notice_daily=2)
    assert answer(session, "sms", OTHER_PHONE, body="일정 알려 주세요") == ("notice", "unknown_accepted")
    set_limits(session, conn, unknown_notice_daily=0)
    assert answer(session, "sms", "010-0000-0009", body="일정 알려 주세요") == ("record", "auto_reply_limit")


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
