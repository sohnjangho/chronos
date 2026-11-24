"""상황 × 열 격자(Task 86 글 열 · Task 97 음성 열). CELLS 는 설계 표의 표시 그대로, run_cell 은 한 칸을 임시 DB 에서 돌린다
(broken 이면 그 칸을 지키는 곳 하나를 그 실행 안에서만 무르고 — 글 열은 drive_text, 음성 열은 drive_voice 가 **같은 대본**을 돈다).
run_all 은 네 열 전부. CHANNEL_ONLY 는 한 채널에만 있는 경우 — 문자 · 통화(가짜 통화) · 카카오톡(가짜 통로·가짜 제공사만 — 실제
알림톡은 쓰지 않는다). 경우마다 대본의 표시가 있는 열 하나로 돈다.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal

from app.outreach.harness import tools
from app.outreach.scenarios import drive_text, drive_voice
from app.outreach.scenarios.drive_text import CellResult
from app.outreach.scenarios.situations import (
    COLUMNS,
    SITUATIONS,
    TEXT_RULE_LINE,
    Check,
    Column,
    G,
    Mark,
    Model,
    ModelSays,
    Setup,
    Situation,
    Them,
    Wait,
    World,
    _fell_back,
    limits,
    marks,
)
from app.outreach.voice import call_run

CELLS: Mapping[tuple[str, Column], Mark] = {(s.id, column): s.marks[column] for s in SITUATIONS for column in COLUMNS}
_BY_ID = {s.id: s for s in SITUATIONS}
SMS_BYTES = 90  # 설계·화면(smsLength.ts)과 같은 SMS 한 건의 바이트


@dataclass(frozen=True)
class Case:
    """한 채널에만 있는 경우. situation 의 표시가 있는 열 하나로 돈다(문자 sms_in · 통화 call_out/call_in · 카카오톡 sms_reply)."""

    id: str
    medium: Literal["sms", "call", "kakao"]
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
_OUT_ONLY = marks("run", "none", "none", "none")
_IN_ONLY = marks("none", "run", "none", "none")
_REPLY_ONLY = marks("none", "none", "none", "run")
_TIME_LIMIT_S = 30  # 최대 통화 시간 경우의 상한(말이 이어지는 대본 — 침묵 없이 넘긴다)


def _agent_lines(w: World, index: int = 0) -> list[str]:
    return [line["text"] for line in w.call(index).transcript_json if line["role"] == "agent"]


def _by_agent(w: World, index: int = 0) -> bool:
    """그 통화는 우리 쪽(모델·코드)이 끝냈다."""
    return [reason for reason, _ in w.voices[index].ended] == ["agent"]


def _voicemail_sms(w: World) -> list:
    return [(m.channel, m.status, m.call_id, m.body) for m in w.out(kind="normal") if m.call_id is not None]

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
    Case("voicemail", "call", "음성사서함·자동응답 → 남기지 않고 종료, 문자 초안", ("V-04",),
         Situation("voicemail", "음성사서함", _OUT_ONLY, Setup(limits()),
                   (Them("지금은 전화를 받을 수 없습니다. 삐 소리가 나면 메시지를 남겨 주세요"),
                    Model("end_call", {"reason": "voicemail"})),
                   (Check("남긴 말 없음 — 우리 말은 첫마디 하나뿐이고 통화는 우리 쪽이 끝냈다",
                          lambda w: len(_agent_lines(w)) == 1 and _by_agent(w) and w.call(0).status == "completed"),
                    G("문자 초안 한 줄 — 그 통화에 붙고, 승인 받기라 초안·통로 0",
                      lambda w: _voicemail_sms(w) == [("sms", "draft", w.call(0).id,
                                                       tools.VOICEMAIL_SMS.format(site="가람 현장"))]
                      and w.delivered == [])),
                   (), {"call_out": "gate.permission"})),
    Case("wrong_number", "call", "잘못된 번호 → 번호 오류 표시", ("V-05",),
         Situation("wrong_number", "잘못된 번호", _OUT_ONLY, Setup(limits(), probes=("call:park",)),
                   (Them("여기 그런 사람 없어요. 잘못 거셨어요"), Model("end_call", {"reason": "wrong_number"})),
                   (Check("연락처 번호가 잘못된 번호로 표시된다(phone_invalid) — 통화는 우리 쪽이 끝냈다",
                          lambda w: w.person("park").phone_invalid is True and _by_agent(w)),
                    Check("그 뒤 그 사람에게 거는 전화는 문이 받지 않는다(not_sendable)",
                          lambda w: w.probe("call:park")[0] == "not_sendable")),
                   (), {})),
    Case("silence", "call", "침묵·통화 품질 → 두 번 확인 후 종료", ("V-14",),
         Situation("silence", "침묵", _OUT_ONLY, Setup(limits()),
                   (Them("여보세요"), Wait(60)),
                   (G("「들리시나요」 두 번 뒤 마치는 말을 하고 끊는다(silence 사건 셋)",
                      lambda w: w.code_said(0) == [call_run.HELLO, call_run.HELLO, call_run.GIVE_UP]
                      and [d for n, _, d in w.log(w.call(0)) if n == "silence"]
                      == ["침묵 확인 1", "침묵 확인 2", "침묵으로 끊음"] and _by_agent(w)),
                    G("침묵으로 끝난 통화도 통화됨(completed) — 길이는 침묵 확인 셋만큼(15초씩)",
                          lambda w: w.call(0).status == "completed" and w.call(0).duration_s == 2 + 3 * call_run.SILENCE_S)),
                   (), {"call_out": "call.silence"})),
    Case("call_time_limit", "call", "최대 통화 시간 초과 → 정리 멘트 후 종료", ("V-15",),
         Situation("call_time_limit", "최대 통화 시간", _OUT_ONLY, Setup(limits(max_call_seconds=_TIME_LIMIT_S)),
                   tuple(step for n in range(1, 11) for step in (Them(f"그리고 {n}번째로 말씀드릴 게 있는데요"),
                                                                  ModelSays("네 말씀하세요"))),
                   (G("최대 시간 20초 전에 정리 말 한 번, 닿으면 끊는다(time_limit 사건 둘)",
                      lambda w: w.code_said(0) == [call_run.WRAP_UP]
                      and [d for n, _, d in w.log(w.call(0)) if n == "time_limit"] == ["정리 안내", "최대 통화 시간"]
                      and _by_agent(w) and w.call(0).duration_s == _TIME_LIMIT_S),),
                   (), {"call_out": "call.time_limit"}),
         limits=limits(max_call_seconds=_TIME_LIMIT_S)),
    Case("misdial_or_ad", "call", "잘못 건 전화·광고 → 짧게 마치고 기록", ("R-10",),
         Situation("misdial_or_ad", "잘못 건 전화·광고", _IN_ONLY, Setup(limits()),
                   (Them("안녕하세요 고객님, 저금리 대출 상품을 안내해 드리려고 연락드렸습니다", sender="stranger"),
                    Model("end_call", {"reason": "other"})),
                   (Check("짧게 끝 — 모르는 번호로 받아 우리 쪽이 곧바로 끝냈다(기록은 통화 줄 하나)",
                          lambda w: w.call(0).caller_class == "unknown" and w.call(0).status == "completed"
                          and _by_agent(w) and w.call(0).duration_s <= 10),
                    Check("메모 없음 — 메모·제안·후속 줄이 없다",
                          lambda w: w.reports("message") == [] and w.proposals("new") == [] and w.out() == []
                          and w.calls_to("park") == [])),
                   (), {})),
    Case("kakao_not_ready", "kakao", "카카오톡이 준비되지 않음 → 문자로 나감(나가는 문 차례 7)", (),
         Situation("kakao_not_ready", "카카오톡 준비 안 됨", _REPLY_ONLY, Setup(limits(), request_channel="kakao"),
                   (Them("네 확인했습니다"), ModelSays("감사합니다")),
                   (Check("우리 요청(카카오톡)이 문자로 대신 나간다 — fallback_sms · kakao_not_ready · 통로는 문자",
                          lambda w: _fell_back(w) and w.out(id=w.request_id)[0].channel == "sms"),),
                   (), {})),
    Case("kakao_fell_back", "kakao", "카카오톡 실패 → 문자로 대신 보냄 표시(일꾼의 fell_back)", (),
         Situation("kakao_fell_back", "카카오톡 실패·대신 보냄", _REPLY_ONLY,
                   Setup(limits(), request_channel="kakao", kakao_template=True, status_results=("fell_back:3104",)),
                   (Them("네 확인했습니다"), ModelSays("감사합니다")),
                   (Check("승인된 문안이면 카카오톡(가짜 통로)으로 나가고, 문이 문자로 바꾸지 않는다",
                          lambda w: [(m.channel, "kakao_not_ready" in w.rules(m)) for m in w.out(id=w.request_id)]
                          == [("kakao", False)]),
                    Check("일꾼의 상태 조회가 「실패·문자로 대신 나감」을 보면 failed 와 「문자로 대신 보냄」 표시(fallback_sms)",
                          lambda w: [(m.status, m.fallback_sms) for m in w.out(id=w.request_id)] == [("failed", True)]
                          and ("delivery_update", "blocked", "failed") in w.log(w.out(id=w.request_id)[0]))),
                   (), {})),
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
    from app.outreach.scenarios.breaks import BREAKS, VOICE_BREAKS

    with {**BREAKS, **VOICE_BREAKS}[situation.guards[column]]():
        return await _run(situation, column)


def case_column(case: Case) -> Column:
    """경우가 도는 열 — 대본의 표시가 있는 열 하나."""
    return next(column for column in COLUMNS if case.situation.marks[column] != "none")


async def run_case(case_id: str, *, broken: bool = False) -> CellResult:
    """한 채널에만 있는 경우 하나(표시가 있는 그 열로). broken 이면 그 경우를 지키는 곳(있을 때만)을 그 실행 안에서만 무른다."""
    case = _CASES[case_id]
    column = case_column(case)
    if not broken:
        return await _run(case.situation, column)
    from app.outreach.scenarios.breaks import BREAKS, VOICE_BREAKS

    with {**BREAKS, **VOICE_BREAKS}[case.situation.guards[column]]():
        return await _run(case.situation, column)


async def _run(situation: Situation, column: Column) -> CellResult:
    with drive_text.temp_database() as factory:
        if column in drive_voice.VOICE_COLUMNS:
            return await drive_voice.run(situation, column, factory)
        return await drive_text.run(situation, column, factory)


async def run_all() -> dict[tuple[str, Column], CellResult]:
    """네 열 전부 — 설계 표에서 「none」이 아닌 칸마다 한 번(무르기 없이)."""
    return {(sid, column): await run_cell(sid, column) for (sid, column), mark in CELLS.items() if mark != "none"}
