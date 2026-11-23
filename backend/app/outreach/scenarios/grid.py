"""상황 × 열 격자(Task 86 — 글 열). CELLS 는 설계 표의 표시 그대로, run_cell 은 한 칸을 임시 DB 에서 돌린다(broken 이면 그
칸을 지키는 곳 하나를 그 실행 안에서만 무르고). CHANNEL_ONLY 는 한 채널에만 있는 경우 — 문자 것은 여기서 돌고, 통화 것은
Task 97 이 같은 꼴로 채운다(지금은 대본 없이 이름·옛 번호·상한만).
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal

from app.outreach.scenarios import drive_text
from app.outreach.scenarios.drive_text import CellResult
from app.outreach.scenarios.situations import (
    COLUMNS,
    SITUATIONS,
    TEXT_RULE_LINE,
    Check,
    Column,
    Mark,
    ModelSays,
    Setup,
    Situation,
    Them,
    World,
    limits,
    marks,
)

CELLS: Mapping[tuple[str, Column], Mark] = {(s.id, column): s.marks[column] for s in SITUATIONS for column in COLUMNS}
_BY_ID = {s.id: s for s in SITUATIONS}
SMS_BYTES = 90  # 설계·화면(smsLength.ts)과 같은 SMS 한 건의 바이트


@dataclass(frozen=True)
class Case:
    """한 채널에만 있는 경우. situation 은 문자 경우의 대본(sms_in 열로 돈다) — 통화 경우는 None(Task 97)."""

    id: str
    medium: Literal["sms", "call"]
    title: str
    refs: tuple[str, ...]
    situation: Situation | None = None
    limits: Mapping[str, int] | None = None


def _sms_bytes(text: str) -> int:
    """화면의 smsLength 와 같은 셈: NFC · 앞뒤 공백을 뺀 뒤 ASCII 1 · 그 밖 2 바이트."""
    import unicodedata

    return sum(1 if ord(ch) < 0x80 else 2 for ch in unicodedata.normalize("NFC", text).strip())


def _same_bytes(w: World) -> bool:
    """문자 통로의 길이 종류(channels.sms.length_kind)가 화면의 셈과 같은 답을 준다 — 이번 답과 견본들."""
    # 불러오면 진짜 문자 통로가 등록된다 — 쓰는 때에만(대본 동안은 가짜가 앞에 선다)
    from app.outreach.channels.sms import length_kind

    samples = [r.body for r in w.replies()] + ["네", "가" * 45, "가" * 46, "a" * 90, "a" * 91, "작업 시간 확인 OK"]
    return all(length_kind(text) == ("sms" if _sms_bytes(text) <= SMS_BYTES else "long") for text in samples)


_LONG = ("작업 시간은 담당자가 확인한 뒤 다시 알려드리겠습니다. 현장 사정에 따라 시간이 바뀔 수 있습니다. "
         "확정되면 바로 문자로 알려드리겠습니다")
_TEXT_ONLY = marks("none", "none", "run", "none")

CHANNEL_ONLY: list[Case] = [
    Case("sms_length", "sms", "길이·나눠 보내기 — 긴 답은 두 문장까지, 바이트 셈은 화면(smsLength)과 같다", (),
         Situation("sms_length", "길이·나눠 보내기", _TEXT_ONLY, Setup(limits()),
                   (Them("작업 몇 시에 시작해요?"), ModelSays(_LONG)),
                   (Check("지시문에 「두 문장까지」 줄이 있다", lambda w: TEXT_RULE_LINE in w.instructions(0)),
                    Check("긴 답도 한 줄(나눠 보내지 않음) — 길이는 long",
                          lambda w: [_sms_bytes(r.body) > SMS_BYTES for r in w.replies()] == [True]),
                    Check("문자 통로의 길이 셈이 화면의 셈과 같다", _same_bytes)),
                   (), {})),
    Case("machine_text", "sms", "기계가 보낸 문자(인증번호·광고) → 답하지 않음", ("T-07",),
         Situation("machine_text", "기계가 보낸 문자", _TEXT_ONLY, Setup(limits(), permission="delegate"),
                   (Them("[Web발신] 인증번호 123456", sender="stranger"), ModelSays("네")),
                   (Check("기록만(machine_text) — 세션도 답도 없다",
                          lambda w: w.admission(w.inbound()[0]) == ("blocked", "machine_text") and not w.opened(0)
                          and w.replies() == []),),
                   (), {})),
    Case("photo", "sms", "사진이 붙은 문자 → 기록만(판독하지 않음)", ("T-12",),
         Situation("photo", "사진 첨부", _TEXT_ONLY, Setup(limits(), permission="delegate"),
                   (Them("사진 보냅니다", media=True), ModelSays("네")),
                   (Check("기록만(media_attached) — 세션도 답도 없다",
                          lambda w: w.admission(w.inbound()[0]) == ("blocked", "media_attached") and not w.opened(0)
                          and w.replies() == []),),
                   (), {})),
    Case("voicemail", "call", "음성사서함·자동응답 → 남기지 않고 종료, 문자 초안", ("V-04",)),
    Case("wrong_number", "call", "잘못된 번호 → 번호 오류 표시", ("V-05",)),
    Case("silence", "call", "침묵·통화 품질 → 두 번 확인 후 종료", ("V-14",)),
    Case("call_time_limit", "call", "최대 통화 시간 초과 → 정리 멘트 후 종료", ("V-15",),
         limits=limits(max_call_seconds=300)),
    Case("misdial_or_ad", "call", "잘못 건 전화·광고 → 짧게 마치고 기록", ("R-10",)),
]
_CASES = {case.id: case for case in CHANNEL_ONLY}


async def run_cell(situation_id: str, column: Column, *, broken: bool = False,
                   limits: Mapping[str, int] | None = None) -> CellResult:
    """한 칸. broken 이면 그 칸을 지키는 곳(Situation.guards[열])을 그 실행 안에서만 무른다(breaks — 시험·모래상자에서만).
    limits 를 주면 대본의 상한 가운데 그 칸만 바꿔 돌린다(상한이 결과를 바꾸는지 볼 때)."""
    situation = _BY_ID[situation_id]
    if limits:
        situation = replace(situation, setup=replace(situation.setup, limits={**situation.setup.limits, **limits}))
    if not broken:
        return await _run(situation, column)
    # 무르기는 시험·모래상자 프로세스에서만 불러올 수 있다
    from app.outreach.scenarios.breaks import BREAKS

    with BREAKS[situation.guards[column]]():
        return await _run(situation, column)


async def run_case(case_id: str) -> CellResult:
    """문자에만 있는 경우 하나(sms_in 열로)."""
    case = _CASES[case_id]
    if case.situation is None:
        raise ValueError("이 경우는 통화 경우입니다(Task 97)")
    return await _run(case.situation, "sms_in")


async def _run(situation: Situation, column: Column) -> CellResult:
    with drive_text.temp_database() as factory:
        return await drive_text.run(situation, column, factory)
