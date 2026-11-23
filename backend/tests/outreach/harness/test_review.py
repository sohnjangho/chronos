"""뒤 확인(Task 68): 에이전트가 한 말·보내려는 글을 상대가 실제로 한 말과 도구가 실제로 돌려준 것에 견준다.

지키는 것은 하나 — 틀린 「깨끗함」이 없어야 한다. 그래서 헷갈리면 깃발이다(상대 말이 없음·상한을 넘음·근거 말이 없는 답·
읽을 수 없는 날짜 꼴). 번호·이름·회사는 모두 가상이다(이름표의 SENTINEL_PHONE).
"""

import time
from dataclasses import dataclass
from datetime import date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import db
from app.core.model import Activity, CalendarSpec, Relation, Schedule, WbsNode
from app.outreach.harness import events, facts, review
from app.outreach.harness.review import Verdict, check, heard
from app.outreach.harness.types import REVIEW_FLAGS, Candidate, Ref, Scope
from app.store import outreach as store
from app.store.outreach import KST, NotFound
from app.store.schedules import create_schedule
from app.store.tables_outreach import (
    Contact,
    ContactCompany,
    ContactReport,
    OutreachCall,
    OutreachMessage,
)
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_PHONE

NOW = datetime(2026, 11, 24, 10, 0, tzinfo=KST)  # 화요일. 11월 28일은 그 주 토요일
FACT = [{"items": [{"id": "R", "name": "가람동 철근 배근", "start": "2026-11-28", "finish": "2026-12-01", "status": "on_plan"}]}]
PEER = ["네 토요일은 6명 가능합니다"]
UNKNOWN = Scope("unknown", (), (), False, "none")


# ── 도우미 ───────────────────────────────────────────────────────────


def site(session: Session, name: str, mark: str) -> int:
    """일정 하나: 골조 WBS 에 R 「<표식> 철근 배근」, 설비 WBS 에 E 「<표식> 전기 배선」·N 「전기 배선」·W 「<표식> 방수」·
    S 「양생」(짧은 이름)·C 「<표식> 준공 청소」·P 「<표식> 전기 배선 철근 관통부」, 그리고 마일스톤 Z 「<표식> 준공」."""
    schedule = Schedule(
        start=date(2026, 11, 26), calendar=CalendarSpec(days_per_week=5),
        wbs=(WbsNode("1", "골조", None), WbsNode("2", "설비", None)),
        activities=(
            Activity("R", f"{mark} 철근 배근", "task", "1", 3), Activity("E", f"{mark} 전기 배선", "task", "2", 2),
            Activity("N", "전기 배선", "task", "2", 1), Activity("W", f"{mark} 방수", "task", "2", 1),
            Activity("S", "양생", "task", "2", 1), Activity("C", f"{mark} 준공 청소", "task", "2", 1),
            Activity("P", f"{mark} 전기 배선 철근 관통부", "task", "2", 1), Activity("Z", f"{mark} 준공", "finish_ms", "1", 0),
        ),
        relations=(Relation("R", "E"), Relation("E", "N"), Relation("N", "W"), Relation("W", "S"), Relation("S", "C"),
                   Relation("C", "P"), Relation("P", "Z")),
        resources=(),
    )
    return create_schedule(session, name=name, domain="construction", level="L3", schedule=schedule, conditions=[],
                           by_kind="agent", by_name="에이전트", note="처음 만듦")


@dataclass
class World:
    a: int
    b: int
    firm: ContactCompany
    park: Contact
    scope: Scope  # 박현장(가람 현장 철근) — 연락처 등급


def world(session: Session) -> World:
    a, b = site(session, "가람 현장", "가람동"), site(session, "나래 현장", "나래동")
    firm = ContactCompany(schedule_id=a, name="가람철근", trade="철근")
    session.add(firm)
    session.flush()
    park = Contact(schedule_id=a, company_id=firm.id, name="박현장", phone=SENTINEL_DIGITS)
    session.add(park)
    session.flush()
    return World(a, b, firm, park, Scope("contact", (a,), (Candidate(a, park.id, firm.id),), True, "trade"))


def row(session: Session, kind: str = "call", to: Contact | None = None, **over) -> Ref:
    """통화 한 통 또는 들어온 문자 한 건(뒤 확인이 붙는 줄)."""
    link = {} if to is None else {"schedule_id": to.schedule_id, "contact_id": to.id}
    if kind == "call":
        made = OutreachCall(origin="agent", purpose="타설 인원 확인", **link, **over)
    else:
        made = OutreachMessage(direction="in", channel="sms", origin="peer", status="received", body="받은 글", **link, **over)
    session.add(made)
    session.commit()
    return Ref(kind, made.id)


def run(session: Session, ref: Ref, said: list[str], *, scope: Scope = UNKNOWN, peer=PEER, tools=(), **over) -> Verdict:
    return check(session, ref, said=said, peer_lines=list(peer), tool_results=list(tools), scope=scope, now=NOW, **over)


def reports(session: Session, ref: Ref, kind: str = "review") -> list[ContactReport]:
    link = ContactReport.call_id if ref.kind == "call" else ContactReport.message_id
    return list(session.scalars(select(ContactReport).where(link == ref.row_id, ContactReport.kind == kind)))


def answers(session: Session, ref: Ref) -> list[dict]:
    session.expire_all()
    return session.get(OutreachCall if ref.kind == "call" else OutreachMessage, ref.row_id).answers_json


def answer(quote: str) -> dict:
    return {"question": "토요일 인원", "answer": "6명 가능", "quote": quote, "quote_found": False}


# ── heard: 상대가 그 말을 했는가 ─────────────────────────────────────


def test_heard_exact_and_loose():
    assert heard("토요일 6명 가능", ["네 토요일은 6명 가능합니다"]) and not heard("일요일도 가능", ["일요일은 안 됩니다"])


@pytest.mark.parametrize(("quote", "line"), [
    ("네 토요일은 6명 가능합니다", "네 토요일은 6명 가능합니다"),
    ("토요일 6명 가능", "네, 토요일은… 6명 가능합니다."),  # 문장부호
    ("토요일 6명 가능", "네 토요일은 ６명 가능합니다"),  # 전각 숫자
    ("토요일은 6명이 가능", "네 토요일 6명 가능합니다"),  # 조사는 어느 쪽에 있든
    ("토요일 6명 가능", "네 토요일은 6명가능합니다"),  # 띄어쓰기
    ("일요일은 안 됩니다", "아뇨 일요일은 안 됩니다"),  # 안 된다는 말을 그대로 든 근거
    ("토요일", "토요일까지 갑니다"),  # 조사로 끝난 말은 뒤집는 말이 아니다
    ("번호는 [번호]", "제 번호는 010-0000-0199 입니다"),  # 저장할 때 가린 근거 말과 가리지 않은 상대 글
    ("내일 오전 자재 반입입니다", "내일 오전 자재 반입임니다"),  # 받아쓰기의 끝 한 글자
])
def test_heard_survives_spacing_punctuation_and_particles(quote, line):
    assert heard(quote, ["여보세요", line, "네 들어가세요"])


@pytest.mark.parametrize(("quote", "line"), [
    ("가능", "토요일은 불가능합니다"),  # 낱말 가운데에서 시작하는 맞음
    ("가능합니다", "토요일은 불가능합니다"),
    ("토요일 6명 가능", "토요일 6명 가능하지 않습니다"),  # 뒤에 뒤집는 말
    ("토요일 6명 가능", "토요일 6명 가능할 것 같지 않아요"),
    ("토요일 6명 가능", "토요일 6명 가능 안 합니다"),
    ("토요일 6명 가능", "토요일 6명 가능은 한데 어렵습니다"),
    ("토요일 6명", "토요일 6명 말고 4명입니다"),
    ("6명 가능", "6명 가능하면 좋겠지만 힘듭니다"),  # 바람·조건
    ("6명 가능", "6명 가능할지는 내일 봐야 압니다"),
    ("6명 가능", "6명 가능하냐고요"),
    ("토요일 가능", "토요일 가능 여부는 미정입니다"),
    ("토요일 가능", "토요일 가능하지만 일요일까지는 무리입니다"),
    ("갑니다", "토요일은 못 갑니다"),  # 앞에 뒤집는 말
    ("토요일 6명 가능", "토요일 6명 가능한가요?"),  # 상대가 물은 말
    ("토요일 6명 가능", "토요일 6명 가능합니까"),
    ("토요일 6명 가능합니다", "일요일 6명 가능합니다"),  # 비슷하지만 요일이 다름
    ("토요일 6명 가능합니다", "토요일 8명 가능합니다"),  # 숫자가 다름
    ("토요일에는 6명 갑니다", "토요일에는 6명 못 갑니다"),  # 비슷하지만 뒤집힘
    ("제가 이 현장 담당자입니다", "제가 이 현장 담당자 아닙니다"),
    ("오전에 들어옵니다", "오후에 들어옵니다"),
    ("6만 개 필요합니다", "6개 필요합니다"),  # 숫자 뒤의 「만」은 조사가 아니다
    ("16만 개 필요합니다", "16개 필요합니다"),
    ("토요일 6명 가능합니다", "토요일 6명 가능합니다?"),  # 글자는 같아도 물음
    ("6 개 필요합니다", "6만 개 필요합니다"),
    ("", "네 토요일은 6명 가능합니다"),
    ("   ", "네 토요일은 6명 가능합니다"),
    ("…?!", "네 토요일은 6명 가능합니다"),
])
def test_heard_refuses_what_the_other_party_did_not_say(quote, line):
    assert not heard(quote, [line])


@pytest.mark.parametrize(("quote", "line"), [
    ("가능", "가능할 수도 있고 아닐 수도 있어요"),  # 흐린 말
    ("토요일 6명 가능", "토요일 6명 가능하다고 들었는데 확인해 볼게요"),  # 남에게 들은 말
    ("6명 가능", "6명 가능했었는데 이제는 무리예요"),  # 지난 일·뒤집힘
    ("토요일 6명", "토요일 6명이라고 하셨죠"),  # 우리 말을 되받음
    ("가능합니다", "가능합니다 라고 하면 거짓말이고요"),
    ("내일 오전에 자재가 들어온다고 합니다", "내일 오전에 자재가 들어온다고 합니다"),  # 전해 들은 말은 근거 말이 같아도
    ("6명 가능합니다", "아마 6명 가능합니다"),
    ("6명 가능합니다", "6명 가능할 것 같습니다"),
    ("6명 가능", "6명 가능할 것 같아요"),
    ("6명 가능", "6명 가능했었어요"),
    ("6명 가능", "6명 가능하대요"),
    ("6명 가능", "6명 가능하던데요"),
])
def test_hedged_or_second_hand_speech_is_not_support(quote, line):
    assert not heard(quote, [line])


def test_heard_has_nothing_to_hear_without_lines():
    assert not heard("토요일 6명 가능", [])
    assert not heard("토요일 6명 가능", ["", "   ", None, 7])  # 글이 아닌 줄은 근거가 아니다
    assert not heard(None, PEER)


def test_heard_reads_only_within_its_caps():
    late = ["네"] * review.MAX_PEER_LINES + ["토요일은 6명 가능합니다"]
    assert not heard("토요일 6명 가능", late)  # 상한 뒤의 줄은 근거가 아니다
    assert not heard("토요일 6명 가능", ["가" * review.MAX_LINE_CHARS + " 토요일은 6명 가능합니다"])
    assert not heard("가" * (review.MAX_QUOTE_CHARS + 1), ["가" * (review.MAX_QUOTE_CHARS + 1)])


# ── 답의 근거 ────────────────────────────────────────────────────────


def test_our_lines_are_not_evidence(session):
    ref = row(session, answers_json=[answer("6명 가능합니다")])

    got = run(session, ref, ["6명 가능합니다 맞으시죠"], peer=["글쎄요 잘 모르겠어요"])

    assert got == Verdict(False, ["unsupported_answer"])
    assert answers(session, ref)[0]["quote_found"] is False


def test_answer_without_quote_is_marked_needs_check(session):
    ref = row(session, answers_json=[answer("토요일은 6명 가능"), answer(""), {"question": "근거 칸이 없는 답", "answer": "네"}])

    got = run(session, ref, ["확인 감사합니다"])

    assert got == Verdict(False, ["unsupported_answer"])
    assert [entry["quote_found"] for entry in answers(session, ref)] == [True, False, False]
    assert answers(session, ref)[0]["answer"] == "6명 가능"  # 다른 칸은 그대로


def test_supported_answer_is_clean_and_marked_found(session):
    ref = row(session, "message", answers_json=[answer("토요일 6명 가능")])

    assert run(session, ref, ["확인 감사합니다"]) == Verdict(True, [])
    assert answers(session, ref)[0]["quote_found"] is True
    assert events.of(session, ref) == [] and reports(session, ref) == []


def test_report_quotes_are_compared_and_reports_without_a_quote_are_left(session):
    ref = row(session)
    made = [store.add_report(session, medium="call", call_id=ref.row_id, kind=kind, text="보고", quote=quote)
            for kind, quote in (("delay", "토요일은 6명 가능합니다"), ("problem", "자재가 안 들어왔습니다"), ("message", ""))]
    other = store.add_report(session, medium="call", call_id=ref.row_id + 1, kind="delay", text="다른 통화", quote="네 토요일은")
    session.commit()

    got = run(session, ref, ["담당자가 확인하도록 전달했습니다"])

    session.expire_all()
    assert [report.quote_found for report in made] == [True, False, False]
    assert other.quote_found is False  # 다른 줄의 보고는 건드리지 않는다
    assert got == Verdict(False, ["unsupported_answer"])  # 근거 말이 상대 말에 없는 보고 하나


def test_message_without_a_quote_is_not_an_unsupported_answer(session):
    """take_message·handoff_to_human 의 메모는 근거 칸이 없는 도구가 남긴다 — 그것만으로는 깃발이 아니다."""
    ref = row(session, "message")
    store.add_report(session, medium="sms", message_id=ref.row_id, kind="message", text="전해 달라는 말", quote="")
    session.commit()

    assert run(session, ref, ["담당자가 확인 후 연락드리겠습니다"]) == Verdict(True, [])


def test_no_peer_line_at_all_is_never_clean(session):
    for peer in ([], ["", "  "], None):
        ref = row(session)
        got = check(session, ref, said=["안녕하세요"], peer_lines=peer, tool_results=[], scope=UNKNOWN, now=NOW)
        assert got == Verdict(False, ["unsupported_answer"])


def test_broken_answer_rows_are_not_clean(session):
    ref = row(session, answers_json=["글 한 줄", answer("토요일 6명 가능")])

    assert run(session, ref, ["네"]) == Verdict(False, ["unsupported_answer"])
    assert answers(session, ref) == ["글 한 줄", {**answer("토요일 6명 가능"), "quote_found": True}]


def test_answers_beyond_the_cap_are_not_clean(session, monkeypatch):
    monkeypatch.setattr(review, "MAX_ANSWERS", 2)
    ref = row(session, answers_json=[answer("토요일 6명 가능")] * 3)

    assert run(session, ref, ["네"]) == Verdict(False, ["unsupported_answer"])
    assert [entry["quote_found"] for entry in answers(session, ref)] == [True, True, False]


# ── 날짜 ─────────────────────────────────────────────────────────────


def test_date_not_from_tool_is_flagged(session):
    ref = row(session)

    assert run(session, ref, ["철근 배근은 11월 30일에 시작합니다"], tools=FACT) == Verdict(False, ["unsupported_date"])
    assert run(session, row(session), ["철근 배근은 11월 28일에 시작합니다"], tools=FACT) == Verdict(True, [])
    assert run(session, row(session), ["11월 28일에 시작합니다"]) == Verdict(False, ["unsupported_date"])  # 도구 결과 없음


@pytest.mark.parametrize("said", [
    "11월 28일", "11월28일까지", "11/28", "2026-11-28", "2026. 11. 28.", "2026년 11월 28일", "26년 11월 28일", "28일",
    "１１월 ２８일", "토요일", "토욜", "28일(토)", "11월 28일 토요일", "이번 주 토요일", "이번 주말", "이번 주", "이번 달 28일",
    "나흘 뒤", "4일 뒤", "4일 후", "11월", "11월 말", "12월 1일", "11월 28일~12월 1일", "11월 28일부터 12월 1일까지",
    "십일월 이십팔일", "십이월 일일", "이십팔일", "올해 11월", "올해", "2026년", "다음 주 화요일", "다음 주", "다음 달",
    "한 달 뒤", "주말", "이번 주말 토요일", "11.28.", "11. 28.", "사일 뒤", "나흘쯤 뒤", "이십팔 일",
])
def test_dates_the_tools_gave_are_supported_in_any_form(session, said):
    assert run(session, row(session), [f"시작은 {said} 입니다"], tools=FACT) == Verdict(True, [])


@pytest.mark.parametrize("said", [
    "11월 29일", "11/29", "2027-11-28", "2026.11.29", "2027년 11월 28일", "25년 11월 28일", "29일", "１１월 ２９일",
    "일요일", "금욜", "28일(금)", "11월 28일 금요일", "다음 주 토요일", "다다음 주", "다음 주말", "지난주", "다음 달 28일",
    "다다음 달", "내일", "모레", "글피", "어제", "오늘", "사흘 뒤", "3일 뒤", "4일 전", "2주 뒤", "두 달 뒤", "10월",
    "11월 27~28일", "28, 29일", "십일월 이십구일", "시월", "이십구일", "내년 3월", "내년", "2027년",
    "2026-13-45", "11월 31일", "13월 5일", "2월 30일", "11/31", "월말", "말일", "연말", "11.29", "26.11.29",
    "11.29.", "11. 29.", "삼일 뒤", "열흘쯤 뒤", "이십구 일", "이번 달 말일", "11월 말일", "주초", "주중", "추석", "설 연휴",
    "성탄절", "연휴", "상반기",
])
def test_dates_from_nowhere_are_flagged_in_any_form(session, said):
    assert run(session, row(session), [f"시작은 {said} 입니다"], tools=FACT) == Verdict(False, ["unsupported_date"])


@pytest.mark.parametrize("said", [
    "11월 28", "11월28에", "11-28", "20261128", "28/11", "11/28~12/1", "12월 초", "12.1", "11월 하순", "11. 28", "11 . 28", "11 .28",
])
def test_more_date_forms_the_tools_gave_are_supported(session, said):
    assert run(session, row(session), [f"시작은 {said} 입니다"], tools=FACT) == Verdict(True, [])


@pytest.mark.parametrize("said", [
    "11월 30", "11월30에", "11-30", "20261130", "30/11", "29/11", "11/28~30", "11월 28~30", "12.1~3", "11월 초", "11월 중순",
    "이번 달 초", "이번 달 30", "12월 하순", "낼", "담주 금요일", "낼모레", "당일", "이튿날", "다음날", "전날", "D-3", "디데이", "어린이날", "공휴일",
    "12월 첫째 주", "11월 마지막 주", "11. 29", "11 . 29", "11 .29", "11. 29 타설",
])
def test_date_like_text_the_reader_used_to_skip_is_not_clean(session, said):
    """읽지 못하던 날짜 꼴(「일」 없는 날·줄표·붙여 쓴 날·날/달 차례·뒤 범위·입말·다른 날에 기댄 말)도 깨끗함이 아니다."""
    assert run(session, row(session), [f"시작은 {said} 입니다"], tools=FACT) == Verdict(False, ["unsupported_date"])


def test_dot_and_space_date_is_read_not_only_its_weekday(session):
    tools = [*FACT, {"when": "11월 23일"}]  # 11월 23일은 월요일

    assert run(session, row(session), ["11. 30(월) 타설"], tools=tools) == Verdict(False, ["unsupported_date"])
    assert run(session, row(session), ["11. 23(월) 타설"], tools=tools) == Verdict(True, [])


def test_colloquial_relative_words_are_read_as_their_day(session):
    tools = [{"when": "11월 25일 15:00"}, {"when": "12월 2일 09:00"}]

    for said in ("낼 15시에 연락드리겠습니다", "담주 수요일에 뵙겠습니다"):
        assert run(session, row(session), [said], tools=tools) == Verdict(True, []), said
    assert run(session, row(session), ["낼모레 뵙겠습니다"], tools=tools) == Verdict(False, ["unsupported_date"])


@pytest.mark.parametrize("said", ["토요일", "내일", "다음 주", "28일", "오늘", "이번 주말", "11월"])
def test_weekday_or_relative_word_needs_a_tool_date(session, said):
    got = run(session, row(session), [f"{said}에 뵙겠습니다"], tools=[{"refused": "말씀드릴 수 없는 내용입니다"}, {"ok": True}])

    assert got == Verdict(False, ["unsupported_date"])


@pytest.mark.parametrize("said", [
    "6명 가능합니다", "3층 2동입니다", "오전 10시 30분에 뵙겠습니다", "15:00 에 연락드리겠습니다", "6개월 걸렸습니다",
    "45일 걸립니다", "일정 안내 드립니다", "무슨 요일인지 확인하겠습니다", "1.5배입니다", "2.5톤입니다", "24/7 운영",
    "회사 월급날은 모릅니다", "입금일은 담당자가 안내합니다", "A-28 구간입니다", "3. 5명 투입합니다", "2.1.3 판입니다",
    "10.20.30 구간입니다",
])
def test_plain_numbers_and_times_are_not_dates(session, said):
    assert run(session, row(session), [said]) == Verdict(True, [])


def test_date_the_other_party_said_is_not_support(session):
    """날짜는 도구가 준 것만 — 상대가 말한 날짜를 되받아 말한 것도 사람이 본다."""
    got = run(session, row(session), ["네 11월 30일로 전달하겠습니다"], peer=["11월 30일에 들어갑니다"], tools=FACT)

    assert got == Verdict(False, ["unsupported_date"])


def test_only_whole_dates_in_tool_results_are_support(session):
    """도구 결과의 글(우리가 보낸 요청 글 등)에서 근거가 되는 것은 달과 날이 든 날짜뿐 — 요일·「내일」·「28일」·「12월」은 아니다."""
    tools = [{"items": [{"channel": "sms", "date": "11월 20일", "text": "내일 28일 토요일 타설 가능하신가요", "activity": None}]},
             {"note": "12월 중 타설 예정"}]

    for said in ("내일 뵙겠습니다", "토요일에 뵙겠습니다", "28일에 뵙겠습니다", "12월에 뵙겠습니다", "12월 28일"):
        assert run(session, row(session), [said], tools=tools) == Verdict(False, ["unsupported_date"]), said
    assert run(session, row(session), ["11월 20일에 보낸 문자 건입니다"], tools=tools) == Verdict(True, [])
    assert run(session, row(session), ["금요일에 보낸 문자 건입니다"], tools=tools) == Verdict(True, [])  # 11월 20일은 금요일


def test_tool_date_without_a_year_is_the_nearest_such_day(session):
    eve = datetime(2026, 12, 30, 10, 0, tzinfo=KST)
    tools = [{"when": "1월 2일 09:00"}]

    def said(text: str) -> Verdict:
        return check(session, row(session), said=[text], peer_lines=PEER, tool_results=tools, scope=UNKNOWN, now=eve)

    assert said("1월 2일에 연락드리겠습니다") == said("2027년 1월 2일") == said("사흘 뒤") == said("토요일") == Verdict(True, [])
    assert said("2026년 1월 2일") == said("금요일") == Verdict(False, ["unsupported_date"])


def test_callback_time_the_tool_gave_supports_relative_words(session):
    tools = [{"when": "11월 25일 15:00", "needs_approval": True}]

    assert run(session, row(session), ["내일 15시에 다시 연락드리겠습니다"], tools=tools) == Verdict(True, [])
    assert run(session, row(session), ["11월 25일 수요일에 연락드리겠습니다"], tools=tools) == Verdict(True, [])
    assert run(session, row(session), ["모레 15시에 다시 연락드리겠습니다"], tools=tools) == Verdict(False, ["unsupported_date"])


def test_date_split_across_lines_is_read_as_one(session):
    assert run(session, row(session), ["시작은 11월", "29일입니다"], tools=FACT) == Verdict(False, ["unsupported_date"])
    assert run(session, row(session), ["시작은 11월", "28일입니다"], tools=FACT) == Verdict(True, [])
    # 줄을 이어 붙여도 다른 달의 28일이 도구의 28일로 지나가지 않는다
    assert run(session, row(session), ["시작은 10월", "28일입니다"], tools=FACT) == Verdict(False, ["unsupported_date"])


def test_one_good_date_does_not_cover_a_bad_one(session):
    got = run(session, row(session), ["11월 28일에 시작해서 12월 5일에 끝납니다"], tools=FACT)

    assert got == Verdict(False, ["unsupported_date"])


def test_tool_results_of_any_shape_never_raise_and_only_dicts_support(session):
    odd = [None, 3, "2026-11-29", ["2026-11-29"], {"x": object(), "y": {1: b"2026-11-29"}, "z": float("nan")},
           {"deep": [[[[[[[[["2026-11-29"]]]]]]]]]}, {"when": date(2026, 11, 28)}, {"at": datetime(2026, 12, 1, 9, 0)}]

    assert run(session, row(session), ["11월 28일과 12월 1일"], tools=odd) == Verdict(True, [])
    assert run(session, row(session), ["11월 29일"], tools=odd) == Verdict(False, ["unsupported_date"])
    got = check(session, row(session), said=["11월 28일"], peer_lines=PEER, tool_results=None, scope=UNKNOWN, now=NOW)
    assert got == Verdict(False, ["unsupported_date"])


def test_tool_results_beyond_the_cap_give_no_support(session, monkeypatch):
    monkeypatch.setattr(review, "MAX_TOOL_VALUES", 5)
    tools = [{"filler": ["가", "나", "다", "라", "마", "바"]}, *FACT]

    assert run(session, row(session), ["11월 28일"], tools=tools) == Verdict(False, ["unsupported_date"])


def test_today_is_the_seoul_day_of_now(session):
    late = datetime(2026, 11, 24, 15, 30)  # 시간대 없는 UTC = 서울 11월 25일 00:30
    tools = [{"when": "11월 25일 09:00"}]

    got = check(session, row(session), said=["오늘 9시"], peer_lines=PEER, tool_results=tools, scope=UNKNOWN, now=late)
    assert got == Verdict(True, [])


# ── 범위 밖 작업 이름 · 금액 ─────────────────────────────────────────


def test_out_of_scope_activity_and_money_are_flagged(session):
    w = world(session)
    ref = row(session, to=w.park)

    got = run(session, ref, ["가람동 전기 배선도 진행 중입니다", "단가는 5만원입니다"], scope=w.scope)

    assert got == Verdict(False, ["out_of_scope_said", "money_said"])


@pytest.mark.parametrize("said", [
    "가람동 철근 배근은 진행 중입니다",  # 공종 말이 든 작업
    "가람동 준공은 예정대로입니다",  # 마일스톤
    "가람동 전기 배선 철근 관통부를 확인했습니다",  # 허용된 이름 안에 든 범위 밖 이름(「전기 배선」)
    "양생은 말씀드릴 수 없습니다",  # 4자보다 짧은 이름은 견주지 않는다
    "나래동 방수는 모릅니다",  # 다른 일정의 이름은 이 규칙이 보지 않는다
    "전기 공사와 배선 작업은 담당자에게 물어보세요",
])
def test_names_allowed_for_this_caller_are_fine(session, said):
    w = world(session)

    assert run(session, row(session, to=w.park), [said], scope=w.scope) == Verdict(True, [])


@pytest.mark.parametrize("said", [
    ["가람동 전기 배선은 진행 중입니다"],
    ["가람동전기배선은요"],  # 띄어쓰기 없이·조사
    ["가 람 동 전 기 배 선"],  # 빈칸을 끼움
    ["가람동-전기·배선"],  # 문장부호를 끼움
    ["가람동\u200b전기\u200b배선"],  # 폭 없는 글자
    ["가람동 전기", "배선입니다"],  # 두 줄에 걸침
    ["전기 배선 말씀이시죠"],  # 「가람동 전기 배선 철근 관통부」(허용) 밖에서 나온 「전기 배선」
    ["가람동 준공 청소까지 끝났습니다"],  # 허용된 이름(「가람동 준공」)을 품은 범위 밖 이름
    ["가람동 방수 일정"],
])
def test_out_of_scope_names_are_found_however_they_are_written(session, said):
    w = world(session)

    assert run(session, row(session, to=w.park), said, scope=w.scope) == Verdict(False, ["out_of_scope_said"])


def test_activity_linked_to_this_persons_rows_is_in_scope(session):
    w = world(session)

    plain = run(session, row(session, to=w.park), ["가람동 방수 건으로 연락드렸습니다"], scope=w.scope)
    linked = run(session, row(session, to=w.park, activity_id="W"), ["가람동 방수 건으로 연락드렸습니다"], scope=w.scope)

    assert (plain, linked) == (Verdict(False, ["out_of_scope_said"]), Verdict(True, []))


def test_scope_that_gives_no_facts_allows_no_name(session):
    w = world(session)
    other = ContactCompany(schedule_id=w.b, name="나래철근", trade="철근")
    session.add(other)
    session.flush()
    choi = Contact(schedule_id=w.b, company_id=other.id, name="박현장", phone=SENTINEL_DIGITS)
    session.add(choi)
    session.flush()
    both = Scope("contact_multi", (w.a, w.b), (*w.scope.candidates, Candidate(w.b, choi.id, other.id)), True, "trade")
    said = ["가람동 철근 배근은 진행 중입니다"]

    assert run(session, row(session), said, scope=both) == Verdict(False, ["out_of_scope_said"])  # 현장을 고르기 전
    assert run(session, row(session), said, scope=both.pinned(w.a)) == Verdict(True, [])
    assert run(session, row(session), ["나래동 철근 배근"], scope=both.pinned(w.a)) == Verdict(True, [])  # 다른 일정은 안 봄
    closed = Scope("shared", (w.a,), w.scope.candidates, False, "none")
    assert run(session, row(session), said, scope=closed) == Verdict(False, ["out_of_scope_said"])


def test_internal_caller_may_name_everything_of_the_pinned_site(session):
    w = world(session)
    staff = Scope("internal", (w.a, w.b), (), False, "all")
    said = ["가람동 전기 배선과 가람동 방수"]

    assert run(session, row(session), said, scope=staff.pinned(w.a)) == Verdict(True, [])
    assert run(session, row(session), said, scope=staff) == Verdict(False, ["out_of_scope_said"])


def test_closed_scope_still_checks_the_rows_schedule(session):
    """통화 도중 연락처가 사라져 범위가 닫혔어도, 그 줄의 일정 이름은 모두 범위 밖이다."""
    w = world(session)
    ref = row(session, to=w.park)

    got = run(session, ref, ["가람동 철근 배근은 진행 중입니다"], scope=UNKNOWN, caller_class="contact")

    assert got == Verdict(False, ["out_of_scope_said", "disclosed_to_unknown"])


def test_allowed_names_come_from_the_tools_rule(session, monkeypatch):
    """허용 규칙은 도구의 facts.allowed_for 하나뿐이다 — 그것이 주는 집합이 그대로 허용이다."""
    w = world(session)
    asked = []

    def fake(session, schedule_id, company_ids, contact_ids):
        asked.append((schedule_id, tuple(company_ids), tuple(contact_ids)))
        return {"E"}

    monkeypatch.setattr(facts, "allowed_for", fake)

    assert run(session, row(session, to=w.park), ["가람동 전기 배선은 진행 중입니다"], scope=w.scope) == Verdict(True, [])
    assert run(session, row(session, to=w.park), ["가람동 철근 배근은 진행 중입니다"], scope=w.scope) == Verdict(
        False, ["out_of_scope_said"])
    assert asked[0] == (w.a, w.scope.company_ids, w.scope.contact_ids)


@pytest.mark.parametrize("said", [
    "5000원", "5,000 원입니다", "3만원", "3만 원", "5천원", "2억", "2억 원", "1억 5천", "300만에 하시죠", "3천만 정도",
    "삼백만 원", "삼백만원입니다", "오천원", "만 원", "수백만 원", "계약금은 드렸습니다", "단가 협의", "평단가",
    "５만원", "₩5000", "$300", "300달러", "일억", "삼천만에 하시죠", "오백만 정도", "5000 won",
])
def test_money_talk_is_flagged(session, said):
    assert run(session, row(session), [f"그 건은 {said}"]) == Verdict(False, ["money_said"])


def test_money_split_across_lines_is_read_as_one(session):
    assert run(session, row(session), ["그 건은 5천", "원 입니다"]) == Verdict(False, ["money_said"])


@pytest.mark.parametrize("said", [
    "6명", "3층", "2동", "5000", "3만 명", "2만 개", "사원", "회사원 6명", "공원 앞", "병원", "직원 6명", "원래 그렇습니다",
    "구원 투수", "조원 3명", "일원화", "300만 화소", "1000", "판단 가능합니다", "수신 차단 가능합니다",
    "한 분만 원하시면 그렇게 전하겠습니다", "하지만 원래 그렇습니다", "천만에요", "그럼 이만 끊겠습니다", "백만 명", "기억합니다",
    "금액은 말씀드릴 수 없습니다",  # 금액을 말하지 않겠다는 말(S-05) — 낱말 「금액」만으로는 깃발이 아니다
])
def test_counts_and_ordinary_words_are_not_money(session, said):
    assert run(session, row(session), [f"그 건은 {said}"]) == Verdict(True, [])


# ── 모르는 상대 ──────────────────────────────────────────────────────


@pytest.mark.parametrize("cls", ["unknown", "withheld", "do_not_contact"])
def test_any_schedule_name_to_unknown_is_flagged(session, cls):
    w = world(session)
    scope = Scope(cls, (), (), False, "none")

    for said in ("나래동 방수는 다음에 합니다", "가람동 철근 배근 말씀이시죠", "가람 현장 담당입니다", "나 래 동 준 공"):
        assert run(session, row(session), [said], scope=scope) == Verdict(False, ["disclosed_to_unknown"]), said
    assert run(session, row(session), ["담당자가 확인 후 연락드리겠습니다"], scope=scope) == Verdict(True, [])
    assert w.a != w.b


def test_names_count_four_characters_with_their_punctuation(session):
    """이름의 길이는 NFC·빈칸을 뺀 글자로 센다 — 「C-1동」(4자)도 견주고, 견줄 글자가 하나도 없는 이름은 모든 말에 걸리지 않는다."""
    site(session, "C-1동", "다온동")
    site(session, "- · - ·", "라온동")

    assert run(session, row(session), ["C-1동 담당입니다"]) == Verdict(False, ["disclosed_to_unknown"])
    assert run(session, row(session), ["담당자가 확인 후 연락드리겠습니다"]) == Verdict(True, [])


def test_do_not_contact_scope_of_a_known_number_gets_both_flags(session):
    w = world(session)
    scope = Scope("do_not_contact", (w.a,), w.scope.candidates, False, "none")

    got = run(session, row(session, to=w.park), ["가람동 철근 배근은 진행 중입니다"], scope=scope)

    assert got == Verdict(False, ["out_of_scope_said", "disclosed_to_unknown"])


def test_known_contact_is_not_judged_as_unknown(session):
    w = world(session)

    assert run(session, row(session, to=w.park), ["가람 현장 가람동 철근 배근"], scope=w.scope) == Verdict(True, [])


def test_class_is_checked_and_the_stricter_of_the_two_wins(session):
    w = world(session)
    said = ["나래동 방수는 다음에 합니다"]

    assert run(session, row(session), said, scope=w.scope, caller_class="do_not_contact").flags == ["disclosed_to_unknown"]
    assert run(session, row(session), said, scope=UNKNOWN, caller_class="internal").flags == ["disclosed_to_unknown"]
    with pytest.raises(ValueError):
        run(session, row(session), said, scope=w.scope, caller_class="관리자")
    with pytest.raises(TypeError):
        check(session, row(session), said=said, peer_lines=PEER, tool_results=[], scope=None, now=NOW)


def test_name_places_beyond_the_cap_are_not_clean(session):
    """허용된 이름이 자리 상한(MAX_SPANS)을 먼저 다 써도, 그 뒤의 범위 밖 이름을 놓치고 깨끗하다고 하지 않는다."""
    w = world(session)
    said = ["가람동전기배선철근관통부" * 100] * (review.MAX_SPANS // 100) + ["전기배선"]
    ref = row(session, to=w.park)

    assert run(session, ref, said, scope=w.scope) == Verdict(False, ["out_of_scope_said"])
    assert [event["detail"] for event in events.of(session, ref)] == ["범위 밖 작업 이름을 말함 · 상한을 넘어 다 견주지 못함"]


def test_name_places_beyond_the_cap_to_unknown_are_marked_unchecked(session):
    world(session)
    ref = row(session)

    assert run(session, ref, ["가람현장" * 400] * 3) == Verdict(False, ["disclosed_to_unknown"])
    assert [event["detail"] for event in events.of(session, ref)] == [
        "모르는 상대에게 일정·작업 이름을 말함 · 상한을 넘어 다 견주지 못함"]


def test_too_many_names_to_compare_is_not_clean(session, monkeypatch):
    w = world(session)
    monkeypatch.setattr(review, "MAX_NAMES", 3)

    assert run(session, row(session, to=w.park), ["네 알겠습니다"], scope=w.scope) == Verdict(False, ["out_of_scope_said"])
    assert run(session, row(session), ["네 알겠습니다"], scope=UNKNOWN) == Verdict(False, ["disclosed_to_unknown"])
    monkeypatch.setattr(review, "MAX_NAMES", 20_000)
    monkeypatch.setattr(review, "MAX_SCHEDULES", 1)
    assert run(session, row(session), ["네 알겠습니다"], scope=UNKNOWN) == Verdict(False, ["disclosed_to_unknown"])


# ── 깨끗한 글 · 같은 형식 · 남기는 것 ────────────────────────────────


def test_clean_text_has_no_flags(session):
    w = world(session)
    ref = row(session, "message", to=w.park, answers_json=[answer("토요일은 6명 가능합니다")])

    got = run(session, ref, ["가람동 철근 배근은 11월 28일 토요일에 시작합니다. 6명으로 전달하겠습니다."], scope=w.scope, tools=FACT)

    assert got == Verdict(True, []) and got.clean
    assert events.of(session, ref) == [] and reports(session, ref) == []


@pytest.mark.parametrize("kind", ["message", "call"])
def test_same_check_for_message_and_call(session, kind):
    w = world(session)
    ref = row(session, kind, to=w.park, answers_json=[answer("일요일도 가능")])
    said = ["가람동 전기 배선은 11월 30일입니다", "계약금은 300만 원입니다"]

    got = run(session, ref, said, scope=w.scope, tools=FACT)

    assert got == Verdict(False, ["unsupported_answer", "unsupported_date", "out_of_scope_said", "money_said"])
    logged = events.of(session, ref)
    assert [(event["rule"], event["detail"], event["evidence"]) for event in logged] == [
        ("unsupported_answer", "답의 근거 말이 상대 말에 없음 · 1건", None),
        ("unsupported_date", "도구 결과에 없는 날짜를 말함 · 1건", None),
        ("out_of_scope_said", "범위 밖 작업 이름을 말함 · 1건", None),
        ("money_said", "금액·계약을 말함 · 2건", None),
    ]
    assert {event["verdict"] for event in logged} == {"blocked" if kind == "message" else "noted"}
    assert all(set(event) == {"rule", "verdict", "detail", "evidence", "at"} for event in logged)
    (line,) = reports(session, ref)
    assert (line.text, line.quote, line.status, line.medium) == ("내용 확인 필요", "", "open", "sms" if kind == "message" else "call")
    assert (line.schedule_id, line.contact_id) == (w.a, w.park.id)


def test_one_event_per_flag_and_one_report_line_however_many_matches(session):
    w = world(session)
    ref = row(session, to=w.park, answers_json=[answer(""), answer("없는 말"), answer("")])
    said = ["가람동 전기 배선 11월 29일, 가람동 방수 11월 30일, 가람동 준공 청소 12월 2일", "단가 5만원, 계약금 3억, 5천원"]

    first = run(session, ref, said, scope=w.scope, tools=FACT)
    second = run(session, ref, said, scope=w.scope, tools=FACT)

    assert first == second == Verdict(False, ["unsupported_answer", "unsupported_date", "out_of_scope_said", "money_said"])
    rules = [event["rule"] for event in events.of(session, ref)]
    assert rules == first.flags * 2  # 부를 때마다 깃발마다 하나씩
    assert {event["detail"] for event in events.of(session, ref)} == {
        "답의 근거 말이 상대 말에 없음 · 3건", "도구 결과에 없는 날짜를 말함 · 3건", "범위 밖 작업 이름을 말함 · 3건",
        "금액·계약을 말함 · 5건"}
    assert len(reports(session, ref)) == 1  # 두 번 불러도 보고는 한 줄


def test_nothing_sensitive_reaches_the_event_or_the_report(session):
    w = world(session)
    ref = row(session, to=w.park, answers_json=[answer(f"제 번호는 {SENTINEL_PHONE} 입니다")])
    said = [f"가람동 전기 배선은 11월 30일이고 단가는 5만원, 번호는 {SENTINEL_PHONE}"]

    got = run(session, ref, said, scope=w.scope, peer=[f"제 번호는 {SENTINEL_PHONE} 이고 비밀표식 이야기입니다"])

    assert set(got.flags) <= REVIEW_FLAGS and not got.clean
    session.expire_all()
    stored = str(events.of(session, ref)) + "".join(f"{line.text}{line.quote}" for line in reports(session, ref))
    for secret in (SENTINEL_PHONE, SENTINEL_DIGITS, "0199", "비밀표식", "전기 배선", "11월", "5만원", "박현장"):
        assert secret not in stored
    assert {event["rule"] for event in events.of(session, ref)} <= REVIEW_FLAGS


def test_check_commits_what_it_wrote(session):
    ref = row(session, answers_json=[answer("토요일 6명 가능"), answer("")])

    run(session, ref, ["11월 30일"])

    with Session(db._engine) as other:  # 다른 세션이 바로 본다
        stored = other.get(OutreachCall, ref.row_id)
        assert [entry["quote_found"] for entry in stored.answers_json] == [True, False]
        assert [event["rule"] for event in stored.harness_json] == ["unsupported_answer", "unsupported_date"]
        assert len(reports(other, ref)) == 1


def test_missing_row_is_an_error_not_a_clean_verdict(session):
    with pytest.raises(NotFound):
        run(session, Ref("call", 987654), ["네"])


# ── 상한 ─────────────────────────────────────────────────────────────


def test_said_cut_by_the_joined_length_is_not_clean(session):
    """줄 글자 수의 합은 상한 안이어도 줄바꿈을 더해 잘리면 끝 줄은 견주지 못한 것이다."""
    w = world(session)
    said = ["네" * 100] * (review.MAX_SAID_LINES - 1) + ["가람동 전기 배선 11월 29일 5만원"]
    assert sum(map(len, said)) <= review.MAX_TEXT_CHARS < len("\n".join(said))

    got = run(session, row(session, to=w.park), said, scope=w.scope)

    assert got == Verdict(False, ["unsupported_date", "out_of_scope_said", "money_said"])


def test_said_beyond_the_caps_is_not_clean(session):
    w = world(session)
    every = ["unsupported_date", "out_of_scope_said", "money_said"]
    too_many = ["네"] * (review.MAX_SAID_LINES + 1)
    too_long = ["네" * (review.MAX_LINE_CHARS + 1)]
    ref = row(session, to=w.park)

    assert run(session, ref, too_many, scope=w.scope) == Verdict(False, every)
    assert {event["detail"] for event in events.of(session, ref)} == {
        "도구 결과에 없는 날짜를 말함 · 상한을 넘어 다 견주지 못함", "범위 밖 작업 이름을 말함 · 상한을 넘어 다 견주지 못함",
        "금액·계약을 말함 · 상한을 넘어 다 견주지 못함"}
    assert run(session, row(session, to=w.park), too_long, scope=w.scope) == Verdict(False, every)
    assert run(session, row(session), ["네", None, 7], scope=UNKNOWN) == Verdict(False, [*every, "disclosed_to_unknown"])
    assert run(session, row(session, to=w.park), too_many[:-1], scope=w.scope) == Verdict(True, [])  # 꼭 상한까지는 본다


def test_a_single_text_is_taken_as_one_line(session):
    got = check(session, row(session), said="단가는 5만원", peer_lines="네 토요일은 6명 가능합니다", tool_results=[],
                scope=UNKNOWN, now=NOW)

    assert got == Verdict(False, ["money_said"])


def test_check_at_the_caps_ends_in_bounded_time(session):
    w = world(session)
    said = ["가람동 철근 배근 11월 28일 6명 " * 4] * review.MAX_SAID_LINES  # 줄 수도 전체 글자 수도 상한 가까이
    peer = ["네 토요일은 6명 가능합니다 " * 6] * review.MAX_PEER_LINES
    assert review.MAX_TEXT_CHARS * 0.8 < sum(map(len, said)) <= review.MAX_TEXT_CHARS
    assert review.MAX_TEXT_CHARS * 0.8 < sum(map(len, peer)) <= review.MAX_TEXT_CHARS
    ref = row(session, to=w.park, answers_json=[answer("없는 말을 길게 지어낸 근거 " * 10)] * review.MAX_ANSWERS)
    started = time.monotonic()

    got = run(session, ref, said, scope=w.scope, peer=peer, tools=FACT * review.MAX_TOOL_VALUES)

    assert time.monotonic() - started < 30
    assert got == Verdict(False, ["unsupported_answer"])
