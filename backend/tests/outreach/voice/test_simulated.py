"""음성 인터페이스와 가짜 통화(Task 87).

세 묶음이다.
1. `VoiceBackendContract` — **인터페이스(VoiceBackend·CallHandlers·CallControl)의 약속**만 보는 시험. 가짜 클래스의 속을 보지
   않고 `make(script)` 와 엿보기 몇 개로만 돈다. SDK 어댑터(Task 113)는 이 클래스를 물려받아 `make` 를 「가짜 SDK 로 같은
   대본을 돌리는 어댑터」로 바꿔 그대로 통과해야 한다(파일 맨 아래 「어댑터가 물려받는 법」).
2. 가짜 통화(SimulatedVoice)에만 있는 것 — 대본 검사·대본 시계·여러 통화·멈춤·모델이 본 글.
3. 통화 명세(CallSpec)·받는 통화(Incoming)·`backend_for`·import 규칙.

번호·이름·음성은 모두 가상이다. 실제 통화·소리·네트워크는 없다.
"""

import ast
import asyncio
import copy
import inspect
import json
import os
import re
import subprocess
import sys
import textwrap
import wave
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import get_args

import pytest

from app.outreach import redact
from app.outreach.harness import registry
from app.outreach.harness.types import CALL_RESULTS, NotReady, ToolDef
from app.outreach.voice import greeting, simulated
from app.outreach.voice import session as voice_session
from app.outreach.voice.session import (
    DECIDE_WITHIN_S,
    END_AGENT,
    END_LOST,
    END_PEER,
    END_REASONS,
    END_TRANSFER,
    END_TRANSFER_FAILED,
    FAIL_CODES,
    OPENING_WITHIN_S,
    TOOL_FAILED_REPLY,
    CallSpec,
    Incoming,
    VoiceBackend,
    VoiceError,
    VoiceInfo,
)
from app.outreach.voice.simulated import (
    Busy,
    Crash,
    Failed,
    Hangup,
    Hold,
    Lost,
    NoAnswer,
    Opening,
    Ring,
    Say,
    Silence,
    SimulatedVoice,
    Tool,
    Transfer,
)
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_PHONE

BACKEND = Path(__file__).resolve().parents[3]
VOICE = BACKEND / "app" / "outreach" / "voice"
OUR_NUMBER = "07000000100"  # 가상 발신번호
STAFF_NUMBER = "01000000155"  # 가상 담당자 번호(전환)
FIRST = "안녕하세요, 가상 물류센터 일정 담당 ChronOS AI 비서입니다. 이 통화는 기록됩니다. 박현장님 맞으신가요?"
RULES = "물어볼 것만 묻는다. 금액·계약은 말하지 않는다."
TOOLS = (
    ToolDef("record_answer", "질문의 답을 적는다",
            {"type": "object", "properties": {"question": {"type": "string"}, "answer": {"type": "string"}}}),
    ToolDef("handoff_to_human", "사람에게 넘긴다", {"type": "object", "properties": {"reason": {"type": "string"}}}),
    ToolDef("end_call", "통화를 마친다", {"type": "object", "properties": {"reason": {"type": "string"}}}),
)


def _digits(text: str) -> str:
    return re.sub(r"[^0-9]", "", text)


def _spec(direction: str = "out", **over) -> CallSpec:
    fields = {
        "direction": direction, "to_number": SENTINEL_DIGITS if direction == "out" else None,
        "from_number": OUR_NUMBER, "language": "ko", "voice_id": "sim-f1", "first_line": FIRST,
        "instructions": RULES, "tools": TOOLS, "max_seconds": 300, "record_to": None,
    }
    return CallSpec(**(fields | over))


class Rec:
    """손잡이를 받은 차례대로 적는다. 걸어 둔 함수가 있으면 그때 부른다(통화 중에 코드가 하는 일을 흉내)."""

    def __init__(self, *, on_start=None, on_transcript=None, on_tool=None, on_tick=None):
        self.log: list[tuple] = []
        self.control = None
        self._hooks = {"start": on_start, "transcript": on_transcript, "tool": on_tool, "tick": on_tick}

    async def _hook(self, kind: str, *args):
        hook = self._hooks[kind]
        return await hook(self.control, *args) if hook else None

    async def on_start(self, control) -> None:
        self.control = control
        self.log.append(("start",))
        await self._hook("start")

    async def on_transcript(self, role, text, t) -> None:
        self.log.append(("transcript", role, text, t))
        await self._hook("transcript", role, text, t)

    async def on_tool(self, name, args) -> dict:
        self.log.append(("tool", name, args))
        result = await self._hook("tool", name, args)
        return {"ok": True} if result is None else result

    async def on_tick(self, elapsed, silent_for) -> None:
        self.log.append(("tick", elapsed, silent_for))
        await self._hook("tick", elapsed, silent_for)

    async def on_end(self, reason, seconds) -> None:
        self.log.append(("end", reason, seconds))

    async def on_failed(self, code, detail) -> None:
        self.log.append(("failed", code, detail))

    def kinds(self) -> list[str]:
        return [entry[0] for entry in self.log]

    def of(self, kind: str) -> list[tuple]:
        return [entry for entry in self.log if entry[0] == kind]

    def quiet(self) -> list[tuple]:
        """시계 알림을 뺀 차례."""
        return [entry for entry in self.log if entry[0] != "tick"]

    def spoken(self) -> list[tuple[str, str]]:
        return [(role, text) for _, role, text, _ in self.of("transcript")]


def _terminals(rec: Rec) -> list[tuple]:
    return [entry for entry in rec.log if entry[0] in ("end", "failed")]


# ══ 1. 인터페이스의 약속 ════════════════════════════════════════════════════════════════════════════════


class VoiceBackendContract:
    """VoiceBackend 를 구현한 것이면 무엇이든 지켜야 하는 약속. 물려받는 쪽이 `make` 와 엿보기를 채운다.

    - `make(script, **options)` — 그 대본(simulated 의 걸음들)대로 「상대와 음성 모델」이 움직이는 백엔드.
      options 는 `decide_within`(받기 전 판정 시한, 초) 하나만 쓴다.
    - 엿보기: 백엔드 밖(전화망·모델 쪽)에서 본 것. `said`(코드가 say 로 시킨 말) · `tool_returns`(모델에게 돌아간 도구 결과)
      · `dialed`(실제로 건 번호) · `transferred_to`(전환을 시작한 번호, 없으면 None) · `rejected`(받지 않고 거절한 전화 수).
    - `SCRIPTED_CLOCK` — 대본이 시계를 미는 백엔드면 True(시각까지 견준다). 실제 시계로 도는 가짜면 False.
    """

    SCRIPTED_CLOCK = True

    def make(self, script: list, **options) -> VoiceBackend:
        raise NotImplementedError

    def said(self, backend) -> list[str]:
        raise NotImplementedError

    def tool_returns(self, backend) -> list[dict]:
        raise NotImplementedError

    def dialed(self, backend) -> list[str]:
        raise NotImplementedError

    def transferred_to(self, backend) -> str | None:
        raise NotImplementedError

    def rejected(self, backend) -> int:
        raise NotImplementedError

    # ── 거는 통화: 차례와 끝 ──────────────────────────────────────────────────────────────────────────

    async def test_script_drives_handlers_in_order(self):
        script = [
            Say("peer", "여보세요", t=2.0),
            Say("agent", "일정 확인차 전화드렸습니다", t=4.0),
            Tool("record_answer", {"question": "타설 가능한가요", "answer": "가능"}),
            Say("peer", "네 가능합니다", t=9.0),
            Hangup("peer"),
        ]
        backend, rec = self.make(script), Rec()
        assert await backend.place(_spec(), rec) is None  # 통화가 끝난 뒤에야 돌아온다
        assert [entry[:3] if entry[0] == "transcript" else entry[:2] for entry in rec.quiet()] == [
            ("start",),
            ("transcript", "agent", FIRST),
            ("transcript", "peer", "여보세요"),
            ("transcript", "agent", "일정 확인차 전화드렸습니다"),
            ("tool", "record_answer"),
            ("transcript", "peer", "네 가능합니다"),
            ("end", END_PEER),
        ]
        assert rec.of("tool")[0][2] == {"question": "타설 가능한가요", "answer": "가능"}
        assert self.dialed(backend) == [SENTINEL_DIGITS]
        if self.SCRIPTED_CLOCK:
            assert [t for *_, t in rec.of("transcript")] == [0.0, 2.0, 4.0, 9.0]
            assert rec.log[-1] == ("end", END_PEER, 9)

    async def test_first_line_is_the_first_thing_said_and_comes_back_as_transcript(self):
        """첫마디는 백엔드가 말한다(대본에 적지 않는다). 실제로 나간 말은 받아쓰기로 돌아온다 — 기록의 첫 줄이 된다."""
        backend, rec = self.make([Say("peer", "네", t=3.0), Hangup("peer")]), Rec()
        await backend.place(_spec(), rec)
        assert rec.kinds()[0] == "start"
        assert rec.of("transcript")[0][1:3] == ("agent", FIRST)
        assert rec.spoken().count(("agent", FIRST)) == 1

    @pytest.mark.parametrize("opening", ["여보세요, 가상 물류센터 김대리입니다. 박현장님 맞으신가요?", ""])
    async def test_opening_that_does_not_disclose_is_caught_in_the_first_utterance(self, opening):
        """첫마디는 모델이 말한다 — 실제 첫 발화가 AI 임·기록됨을 밝히지 않으면(또는 첫 발화가 없으면: 빈 글) 일꾼이 **첫 사건에서**
        알 수 있어야 한다. 그때까지 상대 말·도구는 손잡이에 오지 않았고, 거기서 끊으면 그 뒤도 오지 않는다."""
        spec, before_check = _spec(), []

        async def check_opening(control, role, text, t):
            if not before_check:
                before_check.append(list(rec.log))
                if not greeting.discloses(spec.language, text):
                    await control.hangup()

        script = [Opening(opening), Say("peer", "네 맞습니다", t=2.0), Tool("record_answer", {"question": "q", "answer": "a"}),
                  Hangup("peer")]
        backend, rec = self.make(script), Rec(on_transcript=check_opening)
        await backend.place(spec, rec)
        assert before_check == [[("start",), ("transcript", "agent", opening, 0.0)]]  # 첫 사건이 곧 실제 첫 발화
        assert rec.spoken() == [("agent", opening)] and rec.of("tool") == [] and rec.of("tick") == []
        assert rec.log[-1][:2] == ("end", END_AGENT) and len(_terminals(rec)) == 1
        assert 0 < OPENING_WITHIN_S <= 10

    async def test_opening_that_discloses_lets_the_call_go_on(self):
        said = "안녕하세요 가상 물류센터 일정 담당 크로노스 에이아이 비서입니다 이 통화는 녹음됩니다 박현장님 맞으신가요"
        backend, rec = self.make([Opening(said), Say("peer", "네", t=2.0), Hangup("peer")]), Rec()
        await backend.place(_spec(), rec)
        assert rec.spoken() == [("agent", said), ("peer", "네")] and greeting.discloses("ko", rec.spoken()[0][1])
        assert rec.spoken().count(("agent", FIRST)) == 0  # 받아쓰기는 시킨 말이 아니라 실제로 한 말

    async def test_tool_results_are_recorded(self):
        """모델이 부른 도구는 on_tool 로 오고, on_tool 이 돌려준 dict 가 그대로 모델에게 간다."""
        async def answer(control, name, args):
            return {"ok": True, "tool": name, "echo": args.get("answer")}

        script = [Tool("record_answer", {"question": "q1", "answer": "a1"}), Tool("end_call", {"reason": "done"}),
                  Hangup("agent")]
        backend, rec = self.make(script), Rec(on_tool=answer)
        await backend.place(_spec(), rec)
        assert [entry[1:] for entry in rec.of("tool")] == [("record_answer", {"question": "q1", "answer": "a1"}),
                                                           ("end_call", {"reason": "done"})]
        assert self.tool_returns(backend) == [{"ok": True, "tool": "record_answer", "echo": "a1"},
                                              {"ok": True, "tool": "end_call", "echo": None}]
        assert rec.log[-1][:2] == ("end", END_AGENT)

    async def test_no_answer_and_busy_call_on_failed(self):
        for step, code in ((NoAnswer(), "no_answer"), (Busy(), "busy"), (Failed(), "failed")):
            backend, rec = self.make([step]), Rec()
            assert await backend.place(_spec(), rec) is None
            assert rec.kinds() == ["failed"], code  # 받지 않은 통화: on_start 도 on_end 도 없다
            assert rec.log[0][1] == code
            detail = rec.log[0][2]
            assert isinstance(detail, str) and redact.hide_phones(detail) == detail
            assert SENTINEL_DIGITS not in _digits(detail) and OUR_NUMBER not in _digits(detail)

    def test_fail_codes_are_harness_call_results(self):
        assert FAIL_CODES == ("no_answer", "busy", "failed")
        assert set(FAIL_CODES) < CALL_RESULTS and "backend_error" in CALL_RESULTS - set(FAIL_CODES)
        assert set(END_REASONS) == {END_PEER, END_AGENT, END_TRANSFER, END_TRANSFER_FAILED, END_LOST}
        assert len(END_REASONS) == 5 and not set(END_REASONS) & set(FAIL_CODES)

    @pytest.mark.parametrize("script,kind,word", [
        ([Say("peer", "여보세요", t=1.0), Hangup("peer")], "end", END_PEER),
        ([Say("peer", "여보세요", t=1.0), Hangup("agent")], "end", END_AGENT),
        ([Say("peer", "여보세요", t=1.0), Lost()], "end", END_LOST),
        ([NoAnswer()], "failed", "no_answer"),
        ([Busy()], "failed", "busy"),
        ([Failed()], "failed", "failed"),
    ])
    async def test_every_call_ends_exactly_once_and_last(self, script, kind, word):
        backend, rec = self.make(script), Rec()
        await backend.place(_spec(), rec)
        assert len(_terminals(rec)) == 1 and rec.log[-1][:2] == (kind, word)
        assert rec.kinds().count("start") == (1 if kind == "end" else 0)
        if kind == "end":
            assert rec.kinds()[0] == "start"
            assert type(rec.log[-1][2]) is int and rec.log[-1][2] >= 0
            assert rec.log[-1][1] in END_REASONS
        else:
            assert rec.log[-1][1] in FAIL_CODES

    # ── 통화 중에 코드가 하는 일(CallControl) ────────────────────────────────────────────────────────

    async def test_code_can_say_and_the_line_comes_back_as_agent_transcript(self):
        async def greet_back(control, role, text, t):
            if role == "peer" and text == "누구세요":
                await control.say("일정 담당 AI 비서입니다")

        script = [Say("peer", "누구세요", t=2.0), Say("peer", "아 네", t=5.0), Hangup("peer")]
        backend, rec = self.make(script), Rec(on_transcript=greet_back)
        await backend.place(_spec(), rec)
        assert self.said(backend) == ["일정 담당 AI 비서입니다"]
        assert rec.spoken() == [("agent", FIRST), ("peer", "누구세요"), ("agent", "일정 담당 AI 비서입니다"),
                                ("peer", "아 네")]

    async def test_hangup_by_code_ends_the_call_and_nothing_more_arrives(self):
        async def hang_on_second_line(control, role, text, t):
            if text == "그만하시죠":
                await control.say("알겠습니다. 통화를 마치겠습니다")
                await control.hangup()

        script = [Say("peer", "그만하시죠", t=3.0), Say("peer", "여보세요?", t=6.0),
                  Tool("record_answer", {"question": "q", "answer": "a"}), Silence(30), Hangup("peer")]
        backend, rec = self.make(script), Rec(on_transcript=hang_on_second_line)
        await backend.place(_spec(), rec)
        # 끊기 전에 한 말은 받아쓰기에 남고, 그 뒤의 대본(상대 말·도구·침묵)은 오지 않는다
        assert rec.spoken() == [("agent", FIRST), ("peer", "그만하시죠"), ("agent", "알겠습니다. 통화를 마치겠습니다")]
        assert rec.of("tool") == [] and rec.log[-1][:2] == ("end", END_AGENT)
        assert len(_terminals(rec)) == 1
        if self.SCRIPTED_CLOCK:
            assert rec.log[-1] == ("end", END_AGENT, 3) and all(e[1] <= 3 for e in rec.of("tick"))

    async def test_control_is_harmless_after_the_call_is_over(self):
        """끝난 통화의 손잡이를 쥐고 있다가 불러도(화면의 [통화 끊기]가 한발 늦음) 아무 일도 없고 예외도 없다."""
        backend, rec = self.make([Transfer("answered"), Say("peer", "네", t=1.0), Hangup("peer")]), Rec()
        await backend.place(_spec(), rec)
        before = list(rec.log)
        await rec.control.say("들리시나요")
        await rec.control.hangup()
        await rec.control.hangup()
        assert await rec.control.transfer(STAFF_NUMBER) is False
        assert rec.log == before and self.said(backend) == [] and self.transferred_to(backend) is None

    @pytest.mark.parametrize("outcome,started,reason", [
        ("answered", True, END_TRANSFER),
        ("no_answer", True, END_TRANSFER_FAILED),
        ("refused", False, END_PEER),
    ])
    async def test_transfer_outcomes(self, outcome, started, reason):
        """전환은 코드가 번호를 붙여 시작한다(모델은 번호를 모른다). 시작되면 AI 쪽 통화는 거기서 끝나고, 담당자가 받았는지는
        끝난 까닭으로 온다. 시작하지 못하면 통화가 이어진다."""
        seen: list[bool] = []

        async def hand_off(control, name, args):
            if name == "handoff_to_human":
                seen.append(await control.transfer(STAFF_NUMBER))
                return {"ok": seen[-1]}
            return None

        script = [Say("peer", "담당자 바꿔 주세요", t=2.0), Transfer(outcome),
                  Tool("handoff_to_human", {"reason": "사람 연결 요청"}), Say("peer", "여보세요?", t=8.0),
                  Hangup("peer")]
        backend, rec = self.make(script), Rec(on_tool=hand_off)
        await backend.place(_spec(), rec)
        assert seen == [started]
        assert self.transferred_to(backend) == (STAFF_NUMBER if started else None)
        assert rec.log[-1][:2] == ("end", reason) and len(_terminals(rec)) == 1
        assert (("peer", "여보세요?") in rec.spoken()) is (not started)  # 넘긴 뒤의 말은 우리에게 오지 않는다

    async def test_transfer_is_refused_unless_the_script_says_otherwise(self):
        async def hand_off(control, name, args):
            return {"ok": await control.transfer(STAFF_NUMBER)}

        backend, rec = self.make([Tool("handoff_to_human", {"reason": "r"}), Hangup("peer")]), Rec(on_tool=hand_off)
        await backend.place(_spec(), rec)
        assert self.tool_returns(backend) == [{"ok": False}] and self.transferred_to(backend) is None

    # ── 시계(침묵·경과) ─────────────────────────────────────────────────────────────────────────────

    async def test_tick_gets_silence_seconds(self):
        """on_tick(지난 초, 침묵 초): 침묵은 마지막으로 누가 말한 뒤(어느 쪽이든) 흐른 시간이다."""
        if not self.SCRIPTED_CLOCK:
            pytest.skip("대본 시계가 아닌 백엔드")
        script = [Say("peer", "여보세요", t=2.0), Silence(4), Say("agent", "들리세요", t=7.0), Silence(2), Hangup("peer")]
        backend, rec = self.make(script), Rec()
        await backend.place(_spec(), rec)
        assert rec.of("tick") == [
            ("tick", 1.0, 1.0), ("tick", 2.0, 2.0),  # 첫마디(0초) 뒤
            ("tick", 3.0, 1.0), ("tick", 4.0, 2.0), ("tick", 5.0, 3.0), ("tick", 6.0, 4.0),  # 상대가 2초에 말한 뒤
            ("tick", 7.0, 5.0),
            ("tick", 8.0, 1.0), ("tick", 9.0, 2.0),  # 에이전트가 7초에 말한 뒤
        ]
        assert rec.log[-1] == ("end", END_PEER, 9)

    async def test_silence_checks_can_be_driven_from_ticks(self):
        """일꾼(Task 88)이 할 일을 흉내: 침묵 15초마다 묻고, 세 번째에 끊는다. 코드가 한 말도 침묵을 끊는다."""
        if not self.SCRIPTED_CLOCK:
            pytest.skip("대본 시계가 아닌 백엔드")
        asked = 0

        async def watch(control, elapsed, silent_for):
            nonlocal asked
            if silent_for >= 15:
                asked += 1
                if asked <= 2:
                    await control.say("여보세요, 들리시나요?")
                else:
                    await control.say("잘 들리지 않아 통화를 마치겠습니다")
                    await control.hangup()

        backend, rec = self.make([Silence(120), Hangup("peer")]), Rec(on_tick=watch)
        await backend.place(_spec(), rec)
        assert self.said(backend).count("여보세요, 들리시나요?") == 2
        assert self.said(backend)[-1] == "잘 들리지 않아 통화를 마치겠습니다"
        assert rec.log[-1] == ("end", END_AGENT, 45)
        assert [e[3] for e in rec.of("transcript")] == [0.0, 15.0, 30.0, 45.0]
        assert max(e[2] for e in rec.of("tick")) == 15.0

    async def test_time_limit_can_be_driven_from_ticks(self):
        if not self.SCRIPTED_CLOCK:
            pytest.skip("대본 시계가 아닌 백엔드")
        spec = _spec(max_seconds=60)

        async def watch(control, elapsed, silent_for):
            if elapsed == spec.max_seconds - 20:
                await control.say("시간이 다 되어 정리하겠습니다")
            if elapsed >= spec.max_seconds:
                await control.hangup()

        script = [Say("peer", f"말 {n}", t=float(n * 5)) for n in range(1, 30)] + [Hangup("peer")]
        backend, rec = self.make(script), Rec(on_tick=watch)
        await backend.place(spec, rec)
        assert rec.log[-1] == ("end", END_AGENT, 60)
        assert ("agent", "시간이 다 되어 정리하겠습니다") in rec.spoken()
        # 같은 시각이면 시계 알림이 먼저다 — 60초의 말은 끊긴 뒤라 오지 않는다
        assert ("peer", "말 11") in rec.spoken() and ("peer", "말 12") not in rec.spoken()

    # ── 실패 ───────────────────────────────────────────────────────────────────────────────────────

    @pytest.mark.parametrize("script,started", [
        ([Crash()], False),
        ([Say("peer", "여보세요", t=1.0), Crash(), Hangup("peer")], True),
    ])
    async def test_backend_error_raises_voice_error_without_a_number(self, script, started):
        """백엔드가 고장 나면 place 가 VoiceError 를 올린다(끝 손잡이는 부르지 않는다 — 일꾼이 backend_error 로 닫는다).
        오류 글·원인 사슬 어디에도 번호가 없다."""
        backend, rec = self.make(script), Rec()
        with pytest.raises(VoiceError) as caught:
            await backend.place(_spec(), rec)
        assert _terminals(rec) == [] and (rec.kinds()[:1] == ["start"]) is started
        chain, exc = [], caught.value
        while exc is not None:
            chain.append(exc)
            exc = exc.__cause__ or (None if exc.__suppress_context__ else exc.__context__)
        for exc in chain:
            assert SENTINEL_DIGITS not in _digits(f"{exc!s} {exc!r}") and OUR_NUMBER not in _digits(f"{exc!s} {exc!r}")

    async def test_handler_error_ends_the_call_and_comes_out_of_place(self):
        """손잡이가 예외를 내면 통화를 붙들어 두지 않는다 — 그 예외가 place 밖으로 그대로 나온다."""
        async def broken(control, role, text, t):
            if role == "peer":
                raise RuntimeError("저장 실패")

        script = [Say("peer", "여보세요", t=1.0), Say("peer", "여보세요?", t=2.0), Hangup("peer")]
        backend, rec = self.make(script), Rec(on_transcript=broken)
        with pytest.raises(RuntimeError, match="저장 실패"):
            await backend.place(_spec(), rec)
        assert ("peer", "여보세요?") not in rec.spoken() and _terminals(rec) == []

    async def test_tool_result_must_be_a_json_dict(self):
        """도구 결과는 모델에게 글(JSON)로 간다 — dict 가 아니거나 JSON 으로 못 바꾸면 통화를 잇지 않는다."""
        for bad in ("글", ["a"], {"when": datetime(2026, 11, 23, tzinfo=UTC)}, {"x": object()}):
            async def give(control, name, args, bad=bad):
                return bad

            backend, rec = self.make([Tool("record_answer", {}), Hangup("peer")]), Rec(on_tool=give)
            with pytest.raises(TypeError):
                await backend.place(_spec(), rec)
            assert self.tool_returns(backend) == [] and _terminals(rec) == []

    async def test_place_takes_only_outbound_specs(self):
        backend, rec = self.make([Say("peer", "네", t=1.0), Hangup("peer")]), Rec()
        with pytest.raises(ValueError):
            await backend.place(_spec("in"), rec)
        assert rec.log == [] and self.dialed(backend) == []

    # ── 받는 통화 ──────────────────────────────────────────────────────────────────────────────────

    async def test_ring_returning_none_is_rejected(self):
        """받기 전 판정이 None 이면 받지 않는다 — 통화가 시작되지 않고 그 전화의 대본은 버려진다."""
        offered: list[Incoming] = []

        async def refuse(incoming):
            offered.append(incoming)

        backend = self.make([Ring(SENTINEL_DIGITS), Say("peer", "여보세요", t=1.0), Hangup("peer")])
        await backend.listen(OUR_NUMBER, refuse)
        assert len(offered) == 1 and self.rejected(backend) == 1
        assert offered[0].caller_number == SENTINEL_DIGITS and offered[0].to_number == OUR_NUMBER
        assert offered[0].at.tzinfo is not None

    async def test_answered_ring_runs_like_a_call(self):
        rec = Rec()
        spec = _spec("in", first_line="안녕하세요, 일정 담당 ChronOS AI 비서입니다. 이 통화는 기록됩니다. 무엇을 도와드릴까요?")

        async def answer(incoming):
            return spec, rec

        backend = self.make([Ring(SENTINEL_DIGITS), Say("peer", "타설 날짜가 언제죠", t=3.0),
                             Tool("record_answer", {"question": "q", "answer": "a"}), Hangup("peer")])
        await backend.listen(OUR_NUMBER, answer)
        assert rec.quiet()[0] == ("start",)
        assert rec.spoken() == [("agent", spec.first_line), ("peer", "타설 날짜가 언제죠")]
        assert rec.log[-1][:2] == ("end", END_PEER) and self.rejected(backend) == 0
        assert self.dialed(backend) == []  # 받는 통화는 우리가 거는 것이 아니다

    async def test_withheld_caller_has_no_number(self):
        offered: list[Incoming] = []

        async def refuse(incoming):
            offered.append(incoming)

        backend = self.make([Ring(None), Ring(SENTINEL_DIGITS)])
        await backend.listen(OUR_NUMBER, refuse)
        assert [i.caller_number for i in offered] == [None, SENTINEL_DIGITS] and self.rejected(backend) == 2

    async def test_screening_error_or_delay_means_the_call_is_not_answered(self):
        """받기 전 판정이 예외를 내거나 제때 답하지 못하면 **받지 않는다**(받는 쪽으로 넘어가지 않는다)."""
        rec = Rec()

        async def broken(incoming):
            raise RuntimeError("판정 실패")

        async def stuck(incoming):
            await asyncio.Event().wait()
            return _spec("in"), rec

        for screen in (broken, stuck):
            script = [Ring(SENTINEL_DIGITS), Say("peer", "여보세요", t=1.0), Hangup("peer")]
            backend = self.make(script, decide_within=0.01)
            await backend.listen(OUR_NUMBER, screen)
            assert self.rejected(backend) == 1 and rec.log == []

    async def test_answering_with_an_outbound_spec_is_refused(self):
        rec = Rec()

        async def wrong(incoming):
            return _spec("out"), rec

        backend = self.make([Ring(SENTINEL_DIGITS), Hangup("peer")])
        with pytest.raises(ValueError):
            await backend.listen(OUR_NUMBER, wrong)
        assert rec.log == [] and self.rejected(backend) == 1

    # ── 그 밖 ──────────────────────────────────────────────────────────────────────────────────────

    async def test_check_voices_and_sample_have_the_interface_shapes(self):
        backend = self.make([])
        ok, text = await backend.check()
        assert type(ok) is bool and isinstance(text, str) and text
        listed = await backend.voices("ko")
        assert listed and all(isinstance(v, VoiceInfo) for v in listed)
        assert all(v.gender in ("male", "female", "unknown") and v.id and v.name for v in listed)
        sound = await backend.sample(listed[0].id, "ko", "안녕하세요, 일정 담당 ChronOS AI 비서입니다.")
        assert isinstance(sound, bytes) and sound

    async def test_same_script_gives_the_same_events(self):
        script = [Say("peer", "여보세요", t=1.5), Silence(3), Tool("record_answer", {"question": "q", "answer": "a"}),
                  Say("peer", "네", t=6.0), Hangup("peer")]
        logs = []
        for _ in range(3):
            backend, rec = self.make(copy.deepcopy(script)), Rec()
            await backend.place(_spec(), rec)
            logs.append(rec.log if self.SCRIPTED_CLOCK else rec.quiet())
        assert logs[0] == logs[1] == logs[2] and len(logs[0]) > 5


class TestSimulatedVoiceKeepsTheContract(VoiceBackendContract):
    def make(self, script, **options):
        return SimulatedVoice(script, **options)

    def said(self, backend):
        return backend.said

    def tool_returns(self, backend):
        return [r.result for r in backend.tool_results]

    def dialed(self, backend):
        return backend.dialed

    def transferred_to(self, backend):
        return backend.transferred_to

    def rejected(self, backend):
        return len(backend.rejected)


# ══ 2. 가짜 통화에만 있는 것 ═══════════════════════════════════════════════════════════════════════════


def test_simulated_voice_is_a_voice_backend():
    sim = SimulatedVoice([])
    for name in ("check", "place", "listen", "voices", "sample"):
        assert inspect.iscoroutinefunction(getattr(sim, name))
        assert inspect.iscoroutinefunction(getattr(VoiceBackend, name))
        assert list(inspect.signature(getattr(sim, name)).parameters) == \
            list(inspect.signature(getattr(VoiceBackend, name)).parameters)[1:]


@pytest.mark.parametrize("script,why", [
    ([Say("peer", "여보세요", t=1.0)], "끝나지 않는 통화"),
    ([Say("peer", "여보세요", t=1.0), Hangup("peer"), Silence(3)], "끝난 뒤에 남은 걸음(끝 없음)"),
    ([Say("peer", "a", t=5.0), Say("peer", "b", t=4.0), Hangup("peer")], "시각이 거꾸로"),
    ([Silence(10), Say("peer", "b", t=4.0), Hangup("peer")], "침묵 뒤 시각이 거꾸로"),
    ([Say("peer", "여보세요", t=1.0), NoAnswer()], "말한 뒤의 받지 않음"),
    ([Say("peer", "여보세요", t=1.0), Busy()], "말한 뒤의 통화 중"),
    ([Ring(None), Busy()], "받는 통화의 통화 중"),
    ([Say("peer", "여보세요", t=1.0), Ring(None), Hangup("peer")], "통화 가운데의 벨"),
    ([Say("judge", "여보세요", t=1.0), Hangup("peer")], "모르는 역할"),
    ([Say("peer", "", t=1.0), Hangup("peer")], "빈 말"),
    ([Say("peer", "여보세요", t=-1.0), Hangup("peer")], "음수 시각"),
    ([Silence(0), Hangup("peer")], "0초 침묵"),
    ([Silence(-3), Hangup("peer")], "음수 침묵"),
    ([Hangup("nobody")], "모르는 쪽이 끊음"),
    ([Tool("", {}), Hangup("peer")], "이름 없는 도구"),
    ([Tool("record_answer", ["a"]), Hangup("peer")], "dict 가 아닌 인자"),
    ([Transfer("maybe"), Hangup("peer")], "모르는 전환 결과"),
    ([Ring(SENTINEL_DIGITS, at=datetime(2026, 11, 23, 10, 0)), Hangup("peer")], "시간대 없는 벨 시각"),
    (["여보세요", Hangup("peer")], "걸음이 아닌 것"),
])
def test_script_is_checked_when_the_simulation_is_made(script, why):
    with pytest.raises(ValueError) as caught:
        SimulatedVoice(script)
    assert SENTINEL_DIGITS not in _digits(str(caught.value)), why


@pytest.mark.parametrize("script,why", [
    ([Silence(10**9), Hangup("peer")], "끝없는 침묵"),
    ([Say("peer", "a", t=1e12), Hangup("peer")], "아득한 시각"),
    ([Silence(simulated.CLOCK_CEILING_S), Silence(1), Hangup("peer")], "침묵을 더해 상한을 넘음"),
    ([Silence(float("inf")), Hangup("peer")], "무한 침묵"),
    ([Say("peer", "a", t=float("nan")), Hangup("peer")], "숫자가 아닌 시각"),
    ([NoAnswer()] * (simulated.MAX_STEPS + 1), "너무 긴 대본"),
    ([Say("peer", "a", t=1.0), Opening("b"), Hangup("peer")], "통화 가운데의 첫 발화"),
    ([Opening(None), Hangup("peer")], "글이 아닌 첫 발화"),
])
def test_script_cannot_run_away(script, why):
    """달아나는 대본은 만들 수 없다 — 통화 한 통의 대본 시계와 대본 길이에 끝이 있다."""
    with pytest.raises(ValueError):
        SimulatedVoice(script)
    assert simulated.CLOCK_CEILING_S <= 4 * 3600 and simulated.MAX_STEPS <= 10_000 and simulated.MAX_EVENTS <= 100_000


async def test_longest_allowed_script_clock_stays_inside_the_event_cap():
    sim, rec = SimulatedVoice([Silence(simulated.CLOCK_CEILING_S), Hangup("peer")]), Rec()
    await sim.place(_spec(), rec)
    assert len(rec.log) < simulated.MAX_EVENTS and rec.log[-1] == ("end", END_PEER, int(simulated.CLOCK_CEILING_S))


async def test_handler_that_never_stops_talking_is_cut_off():
    """손잡이가 제 말에 다시 말하는 꼴(끝없는 되풀이)·아주 잦은 시계 알림은 사건 수 상한에서 VoiceError 로 끝난다."""
    async def echo(control, role, text, t):
        if role == "agent":
            await control.say("다시 말씀드리겠습니다")

    sim, rec = SimulatedVoice([Say("peer", "네", t=1.0), Hangup("peer")], max_events=40), Rec(on_transcript=echo)
    with pytest.raises(VoiceError):
        await sim.place(_spec(), rec)
    assert len(rec.log) <= 40 and _terminals(rec) == [] and sim.live == 0 and sim.calls[0].broke
    fine_grained = SimulatedVoice([Silence(simulated.CLOCK_CEILING_S), Hangup("peer")], tick=0.001)
    with pytest.raises(VoiceError):
        await fine_grained.place(_spec(), Rec())
    assert fine_grained.calls[0].seconds < 60 and fine_grained.live == 0
    for bad in (0, -1, simulated.MAX_EVENTS + 1, 2.5):
        with pytest.raises(ValueError):
            SimulatedVoice([], max_events=bad)


async def test_hold_that_is_never_released_ends_by_itself(monkeypatch):
    """Hold·hold_line 은 실제 시간에도 끝이 있다(시험이 놓아주기를 잊어도 통화가 매달려 있지 않는다)."""
    assert 0 < simulated.HOLD_LIMIT_S <= 30
    monkeypatch.setattr(simulated, "HOLD_LIMIT_S", 0.01)
    sim, rec = SimulatedVoice([Hold(), Hangup("peer")]), Rec()
    with pytest.raises(VoiceError):
        await asyncio.wait_for(sim.place(_spec(), rec), 1)
    assert sim.live == 0 and _terminals(rec) == []
    with pytest.raises(VoiceError):
        await asyncio.wait_for(SimulatedVoice([]).wait_held(), 1)

    async def refuse(incoming):
        return None

    held = SimulatedVoice([], hold_line=True)
    with pytest.raises(VoiceError):
        await asyncio.wait_for(held.listen(OUR_NUMBER, refuse), 1)
    assert held.listening is None


def test_script_errors_say_which_step():
    with pytest.raises(ValueError, match="3번째"):
        SimulatedVoice([Say("peer", "a", t=1.0), Hangup("peer"), Say("peer", "b", t=5.0)])


async def test_script_is_copied_so_later_edits_do_not_change_the_run():
    args = {"question": "q", "answer": "a"}
    script = [Tool("record_answer", args), Hangup("peer")]
    sim, rec = SimulatedVoice(script), Rec()
    args["answer"] = "바뀜"
    script.clear()
    await sim.place(_spec(), rec)
    assert rec.of("tool") == [("tool", "record_answer", {"question": "q", "answer": "a"})]


async def test_handler_cannot_change_the_script_through_tool_args():
    async def scribble(control, name, args):
        args["answer"] = "손잡이가 고침"
        return {"ok": True}

    script = [Tool("record_answer", {"question": "q", "answer": "a"}), Hangup("peer")]
    first, second = SimulatedVoice(script), SimulatedVoice(script)
    await first.place(_spec(), Rec(on_tool=scribble))
    rec = Rec()
    await second.place(_spec(), rec)
    assert rec.of("tool")[0][2] == {"question": "q", "answer": "a"}
    assert script[0].args == {"question": "q", "answer": "a"}
    assert first.tool_results[0].args == {"question": "q", "answer": "a"}  # 기록은 모델이 부른 그대로


def test_segments_split_the_script_into_calls():
    script = [NoAnswer(), Say("peer", "네", t=1.0), Hangup("peer"), Ring(None), Ring(SENTINEL_DIGITS),
              Say("peer", "여보세요", t=1.0), Hangup("agent"), Crash()]
    parts = simulated.segments(script)
    assert [[type(step).__name__ for step in part] for part in parts] == [
        ["NoAnswer"], ["Say", "Hangup"], ["Ring"], ["Ring", "Say", "Hangup"], ["Crash"]]


async def test_calls_take_the_script_one_call_at_a_time():
    """대본 하나에 통화 여러 통: 끝 걸음에서 한 통이 끝나고, 다음 place 가 그 뒤를 잇는다(받지 않음 → 다시 걸기 같은 흐름)."""
    sim = SimulatedVoice([NoAnswer(), Say("peer", "여보세요", t=2.0), Hangup("peer"), Busy()])
    assert sim.unused == 3
    first, second, third = Rec(), Rec(), Rec()
    await sim.place(_spec(), first)
    await sim.place(_spec(to_number=STAFF_NUMBER), second)
    await sim.place(_spec(), third)
    assert first.kinds() == ["failed"] and second.kinds()[-1] == "end" and third.log == [("failed", "busy", "busy")]
    assert sim.dialed == [SENTINEL_DIGITS, STAFF_NUMBER, SENTINEL_DIGITS] and sim.unused == 0
    assert sim.failed == [("no_answer", "no_answer"), ("busy", "busy")] and sim.ended == [(END_PEER, 2)]
    assert [call.spec.to_number for call in sim.calls] == sim.dialed
    assert [call.seconds for call in sim.calls] == [0.0, 2.0, 0.0]


async def test_a_call_the_script_does_not_have_is_an_error_and_is_still_counted():
    """대본에 없는 통화가 걸리면(자동으로 다시 걺 등) 숨기지 않는다 — 건 번호는 남고 VoiceError 가 난다."""
    sim = SimulatedVoice([NoAnswer()])
    await sim.place(_spec(), Rec())
    rec = Rec()
    with pytest.raises(VoiceError) as caught:
        await sim.place(_spec(), rec)
    assert isinstance(caught.value, simulated.ScriptExhausted)
    assert sim.dialed == [SENTINEL_DIGITS, SENTINEL_DIGITS] and rec.log == [] and len(sim.calls) == 1
    assert SENTINEL_DIGITS not in _digits(str(caught.value))
    nothing = SimulatedVoice([])
    with pytest.raises(simulated.ScriptExhausted):
        await nothing.place(_spec(), Rec())


async def test_outbound_and_inbound_parts_of_one_script_do_not_mix():
    sim = SimulatedVoice([Ring(SENTINEL_DIGITS), Say("peer", "받는 통화", t=1.0), Hangup("peer"),
                          Say("peer", "거는 통화", t=1.0), Hangup("peer")])
    out_rec, in_rec = Rec(), Rec()
    await sim.place(_spec(), out_rec)

    async def answer(incoming):
        return _spec("in"), in_rec

    await sim.listen(OUR_NUMBER, answer)
    assert ("peer", "거는 통화") in out_rec.spoken() and ("peer", "받는 통화") in in_rec.spoken()
    assert [call.spec.direction for call in sim.calls] == ["out", "in"] and sim.unused == 0


async def test_failed_step_carries_a_fixed_detail_and_refuses_numbers():
    sim, rec = SimulatedVoice([Failed("line_error")]), Rec()
    await sim.place(_spec(), rec)
    assert rec.log == [("failed", "failed", "line_error")]
    with pytest.raises(ValueError):
        SimulatedVoice([Failed(f"{SENTINEL_PHONE} 로 연결하지 못함")])


async def test_tools_outside_the_offered_set_still_reach_the_handler():
    """모델이 받지 않은 도구 이름을 지어내도 가짜는 그대로 넘긴다 — 거절은 하네스 도구 묶음의 몫이고, 그것을 시험할 수 있어야 한다.
    받았던 이름인지는 기록에 남는다."""
    sim, rec = SimulatedVoice([Tool("record_answer", {}), Tool("change_schedule", {"days": 3}), Hangup("peer")]), Rec()
    await sim.place(_spec(), rec)
    assert [(r.name, r.offered) for r in sim.tool_results] == [("record_answer", True), ("change_schedule", False)]
    assert [entry[1] for entry in rec.of("tool")] == ["record_answer", "change_schedule"]


async def test_records_keep_what_the_brief_names():
    async def hand_off(control, name, args):
        await control.say("담당자에게 연결해 드리겠습니다")
        return {"ok": await control.transfer(STAFF_NUMBER)}

    script = [Transfer("answered"), Tool("handoff_to_human", {"reason": "r"}), Hangup("peer"), Ring(SENTINEL_DIGITS)]
    sim, rec = SimulatedVoice(script), Rec(on_tool=hand_off)
    await sim.place(_spec(), rec)

    async def refuse(incoming):
        return None

    await sim.listen(OUR_NUMBER, refuse)
    assert sim.said == ["담당자에게 연결해 드리겠습니다"]
    assert sim.tool_results[0].name == "handoff_to_human" and sim.tool_results[0].result == {"ok": True}
    assert sim.tool_results[0].args == {"reason": "r"}
    assert sim.transferred_to == STAFF_NUMBER and sim.transfers == [(STAFF_NUMBER, "answered")]
    assert sim.ended == [(END_TRANSFER, 0)] and len(sim.rejected) == 1
    assert sim.rejected[0].caller_number == SENTINEL_DIGITS
    assert ("agent", "담당자에게 연결해 드리겠습니다") in rec.spoken()  # 넘기기 전에 한 말은 남는다
    call = sim.calls[0]
    assert call.said == sim.said and call.tool_results == sim.tool_results and call.ended == (END_TRANSFER, 0)
    assert call.transferred_to == STAFF_NUMBER and call.failed is None and not call.overran


async def test_say_after_a_started_transfer_is_not_spoken():
    async def hand_off(control, name, args):
        ok = await control.transfer(STAFF_NUMBER)
        await control.say("연결되었습니다")  # 이미 넘어간 통화 — 말할 수 없다
        await control.hangup()  # 끊을 것도 없다(끝난 까닭이 바뀌지 않는다)
        assert await control.transfer(STAFF_NUMBER) is False
        return {"ok": ok}

    script = [Transfer("answered"), Tool("handoff_to_human", {}), Hangup("peer")]
    sim, rec = SimulatedVoice(script), Rec(on_tool=hand_off)
    await sim.place(_spec(), rec)
    assert sim.said == [] and ("agent", "연결되었습니다") not in rec.spoken()
    assert sim.ended == [(END_TRANSFER, 0)] and sim.transfers == [(STAFF_NUMBER, "answered")]


async def test_call_running_past_its_limit_is_visible():
    """가짜는 최대 통화 시간을 대신 지켜 주지 않는다(일꾼의 몫). 넘겼는지는 기록에서 보인다."""
    sim, rec = SimulatedVoice([Silence(90), Hangup("peer")]), Rec()
    await sim.place(_spec(max_seconds=60), rec)
    assert sim.calls[0].overran and sim.calls[0].seconds == 90.0 and rec.log[-1] == ("end", END_PEER, 90)


async def test_fractional_times_and_tick_size():
    script = [Say("peer", "a", t=0.4), Say("peer", "b", t=1.3), Silence(0.9), Hangup("peer")]
    sim, rec = SimulatedVoice(script, tick=0.5), Rec()
    await sim.place(_spec(), rec)
    assert [e[1] for e in rec.of("tick")] == [0.5, 1.0, 1.5, 2.0]
    assert [round(e[2], 6) for e in rec.of("tick")] == [0.1, 0.6, 0.2, 0.7]
    assert rec.log[-1] == ("end", END_PEER, 2)  # 2.2초 — 초는 내림
    assert [t for *_, t in rec.of("transcript")] == [0.0, 0.4, 1.3]
    for bad in (0, -1.0):
        with pytest.raises(ValueError):
            SimulatedVoice([], tick=bad)


async def test_say_without_a_time_is_spoken_at_once():
    sim, rec = SimulatedVoice([Silence(3), Say("peer", "여보세요"), Say("agent", "네"), Hangup("peer")]), Rec()
    await sim.place(_spec(), rec)
    assert [t for *_, t in rec.of("transcript")] == [0.0, 3.0, 3.0]


async def test_hold_parks_the_call_until_released():
    script = [Say("peer", "잠시만요", t=2.0), Hold(), Say("peer", "네 말씀하세요", t=4.0), Hangup("peer")]
    sim, rec = SimulatedVoice(script), Rec()
    call = asyncio.create_task(sim.place(_spec(), rec))
    await asyncio.wait_for(sim.wait_held(), 1)
    assert sim.live == 1 and not call.done() and ("peer", "네 말씀하세요") not in rec.spoken()
    sim.release()
    await asyncio.wait_for(call, 1)
    assert rec.log[-1] == ("end", END_PEER, 4) and sim.live == 0


async def test_hangup_from_outside_a_handler_ends_a_parked_call():
    """사람이 화면에서 끊는 것처럼 손잡이 밖에서 hangup 을 불러도 통화가 끝난다."""
    script = [Say("peer", "잠시만요", t=2.0), Hold(), Say("peer", "여보세요?", t=9.0), Hangup("peer")]
    sim, rec = SimulatedVoice(script), Rec()
    call = asyncio.create_task(sim.place(_spec(), rec))
    await asyncio.wait_for(sim.wait_held(), 1)
    await rec.control.say("통화를 마치겠습니다")
    await rec.control.hangup()
    await asyncio.wait_for(call, 1)
    assert rec.log[-2:] == [("transcript", "agent", "통화를 마치겠습니다", 2.0), ("end", END_AGENT, 2)]
    assert ("peer", "여보세요?") not in rec.spoken() and sim.live == 0 and sim.unused == 0


async def test_live_calls_are_counted():
    sim = SimulatedVoice([Hold(), Hangup("peer"), Hold(), Hangup("peer")])
    one = asyncio.create_task(sim.place(_spec(), Rec()))
    await asyncio.wait_for(sim.wait_held(), 1)
    two = asyncio.create_task(sim.place(_spec(), Rec()))
    for _ in range(5):
        await asyncio.sleep(0)
    assert sim.live == 2 and sim.peak_live == 2
    sim.release()
    await asyncio.wait_for(asyncio.gather(one, two), 1)
    assert sim.live == 0 and sim.peak_live == 2
    alone = SimulatedVoice([Say("peer", "네", t=1.0), Hangup("peer"), NoAnswer()])
    await alone.place(_spec(), Rec())
    await alone.place(_spec(), Rec())
    assert alone.peak_live == 1 and alone.live == 0


async def test_live_count_drops_when_a_call_breaks():
    async def broken(control, name, args):
        raise RuntimeError("x")

    sim = SimulatedVoice([Tool("record_answer", {}), Hangup("peer"), Crash()])
    with pytest.raises(RuntimeError):
        await sim.place(_spec(), Rec(on_tool=broken))
    with pytest.raises(VoiceError):
        await sim.place(_spec(), Rec())
    assert sim.live == 0 and sim.unused == 0 and [call.broke for call in sim.calls] == [True, True]


async def test_listen_records_the_bound_number_and_can_hold_the_line():
    async def refuse(incoming):
        return None

    sim = SimulatedVoice([Ring(SENTINEL_DIGITS)])
    await sim.listen(OUR_NUMBER, refuse)  # 벨이 떨어지면 돌아온다(실제 백엔드는 취소될 때까지 돌아오지 않는다)
    assert sim.listens == [OUR_NUMBER] and sim.listening is None

    held = SimulatedVoice([Ring(SENTINEL_DIGITS)], hold_line=True)
    task = asyncio.create_task(held.listen(OUR_NUMBER, refuse))
    for _ in range(5):
        await asyncio.sleep(0)
    assert not task.done() and held.listening == OUR_NUMBER and len(held.rejected) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert held.listening is None


async def test_ring_time_is_scripted_not_read_from_the_clock():
    offered: list[Incoming] = []

    async def refuse(incoming):
        offered.append(incoming)

    at = datetime(2026, 11, 27, 18, 30, tzinfo=UTC)
    sim = SimulatedVoice([Ring(SENTINEL_DIGITS), Ring(SENTINEL_DIGITS, at=at)])
    await sim.listen(OUR_NUMBER, refuse)
    assert [i.at for i in offered] == [simulated.RING_AT, at] and simulated.RING_AT.tzinfo is not None


async def test_screening_errors_are_kept_by_type_only():
    async def broken(incoming):
        raise RuntimeError(f"{SENTINEL_PHONE} 판정 실패")

    sim = SimulatedVoice([Ring(SENTINEL_DIGITS), Ring(SENTINEL_DIGITS)], decide_within=0.01)
    await sim.listen(OUR_NUMBER, broken)
    assert sim.screen_errors == ["RuntimeError", "RuntimeError"] and len(sim.rejected) == 2
    assert 0 < DECIDE_WITHIN_S <= 4  # SDK 의 받기 전 결정 시한(5초)보다 짧아야 우리가 먼저 거절한다


def test_simulation_never_reads_a_real_clock_or_randomness():
    """결정적: 가짜는 시계·난수·잠들기를 쓰지 않는다(대본의 시각만). 실제 시간을 기다리는 곳은 끝이 있는 asyncio.wait_for 뿐
    (받기 전 판정의 시한 · Hold·hold_line 의 HOLD_LIMIT_S)이고, 끝없는 기다림(끝 없는 wait)은 그 안에만 있다."""
    tree = ast.parse((VOICE / "simulated.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not imported & {"time", "random", "secrets", "uuid", "threading", "socket", "httpx", "os"}
    called = {node.func.attr for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not called & {"now", "utcnow", "today", "sleep", "monotonic", "time", "perf_counter", "call_later",
                         "call_at", "random", "urandom"}
    # .wait() 는 모두 wait_for 의 인자다 — 끝없이 기다리는 곳이 없다
    bounded = {id(arg) for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr == "wait_for" for arg in node.args[:1]}
    waits = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
             and node.func.attr in ("wait", "gather", "join")]
    assert waits and all(id(node) in bounded for node in waits)
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.While) and isinstance(node.test, ast.Constant)]


async def test_model_saw_lists_every_text_given_to_the_voice_model():
    """모델이 본 글 전부(첫마디·지시문·도구 정의·도구 결과·코드가 시킨 말)를 한곳에서 — 번호가 샜는지 뒤 작업이 여기서 본다."""
    async def leaky(control, name, args):
        if name == "handoff_to_human":
            await control.say(f"담당자 번호는 {SENTINEL_PHONE} 입니다")
            return {"ok": True}
        return {"ok": True, "contact": {"name": "박현장", "phone": SENTINEL_PHONE}}

    sim = SimulatedVoice([Tool("record_answer", {"question": "q", "answer": "a"}), Tool("handoff_to_human", {}),
                          Hangup("peer"), Tool("record_answer", {}), Hangup("peer")])
    await sim.place(_spec(), Rec(on_tool=leaky))
    seen = dict(sim.model_saw())
    assert len(seen) == len(sim.model_saw())  # 이름표는 겹치지 않는다
    assert seen["call 1 first_line"] == FIRST and seen["call 1 instructions"] == RULES
    assert json.loads(seen["call 1 tool record_answer"])["name"] == "record_answer"
    assert SENTINEL_PHONE in seen["call 1 result 1 record_answer"] and SENTINEL_PHONE in seen["call 1 say 1"]
    assert sim.leaks() == ["call 1 result 1 record_answer", "call 1 say 1"]

    await sim.place(_spec(), Rec())
    assert sim.leaks() == ["call 1 result 1 record_answer", "call 1 say 1"]  # 둘째 통화는 깨끗하다
    assert "call 2 result 1 record_answer" in dict(sim.model_saw())
    assert all(SENTINEL_DIGITS not in _digits(label) for label in sim.leaks())


@pytest.mark.parametrize("fault", ["raises", "bad_result"])
async def test_failed_tool_gives_the_model_only_the_fixed_reply(fault):
    """손잡이가 예외를 내거나 틀린 결과를 돌려주면 모델에게는 정해 둔 한 줄만 간다 — 예외 글(번호가 들었을 수 있다)은 가지 않는다."""
    async def broken(control, name, args):
        if fault == "raises":
            raise RuntimeError(f"{SENTINEL_PHONE} 저장 실패")
        return {"when": datetime(2026, 11, 23, tzinfo=UTC), "phone": SENTINEL_PHONE}

    sim = SimulatedVoice([Tool("record_answer", {"question": "q", "answer": "a"}), Hangup("peer")])
    with pytest.raises(RuntimeError if fault == "raises" else TypeError) as caught:
        await sim.place(_spec(), Rec(on_tool=broken))
    seen = dict(sim.model_saw())
    assert seen["call 1 result 1 record_answer"] == TOOL_FAILED_REPLY and sim.leaks() == [] and sim.tool_results == []
    assert all("저장 실패" not in text and SENTINEL_DIGITS not in _digits(text) for text in seen.values())
    assert json.loads(TOOL_FAILED_REPLY)["ok"] is False and not _digits(TOOL_FAILED_REPLY)
    if fault == "bad_result":
        assert SENTINEL_DIGITS not in _digits(str(caught.value))  # 받은 값을 오류 글에 싣지 않는다


async def test_model_is_given_neither_the_dialled_number_nor_what_the_peer_said():
    sim = SimulatedVoice([Say("peer", f"제 번호는 {SENTINEL_PHONE} 입니다", t=1.0),
                          Tool("record_answer", {"question": "q", "answer": "a"}), Hangup("peer")])
    await sim.place(_spec(), Rec())
    text = " ".join(piece for _, piece in sim.model_saw())
    assert SENTINEL_DIGITS not in _digits(text) and OUR_NUMBER not in _digits(text) and sim.leaks() == []


async def test_simulated_voices_and_samples():
    sim = SimulatedVoice([])
    assert [v.id for v in await sim.voices("ko")] == [v.id for v in simulated.SIM_VOICES]
    assert {v.gender for v in simulated.SIM_VOICES} == {"male", "female", "unknown"}
    assert all(v.id.startswith("sim-") for v in simulated.SIM_VOICES)  # 실제 음성 이름이 아니다
    one = await sim.sample("sim-f1", "ko", "안녕하세요")
    assert one == await sim.sample("sim-f1", "ko", "안녕하세요") and one != await sim.sample("sim-f1", "ko", "안녕")
    with wave.open(BytesIO(one)) as sound:  # 들을 수는 있는 꼴(무음) — 실제 소리는 만들지 않는다
        assert sound.getnchannels() == 1 and sound.getnframes() > 0
        assert set(sound.readframes(sound.getnframes())) == {0}
    assert sim.samples == [("sim-f1", "ko", "안녕하세요"), ("sim-f1", "ko", "안녕하세요"), ("sim-f1", "ko", "안녕")]
    with pytest.raises(VoiceError):
        await sim.sample("no-such-voice", "ko", "안녕하세요")

    by_language = SimulatedVoice([], catalogue={"en": [VoiceInfo("sim-en-1", "Sim One", "female")]})
    assert [v.id for v in await by_language.voices("en")] == ["sim-en-1"] and await by_language.voices("ko") == []
    with pytest.raises(VoiceError):
        await by_language.sample("sim-en-1", "ko", "안녕하세요")


async def test_scripted_backend_failures_for_check_voices_and_sample():
    assert await SimulatedVoice([]).check() == (True, "가짜 통화 백엔드")
    down = SimulatedVoice([], broken=("check", "voices", "sample"))
    assert await down.check() == (False, "가짜 통화 백엔드가 꺼져 있습니다(대본)")
    for call in (down.voices("ko"), down.sample("sim-f1", "ko", "안녕하세요")):
        with pytest.raises(VoiceError):
            await call
    with pytest.raises(ValueError):
        SimulatedVoice([], broken=("place",))


def test_simulation_repr_shows_no_number():
    sim = SimulatedVoice([Ring(SENTINEL_DIGITS), Say("peer", f"{SENTINEL_PHONE}", t=1.0), Hangup("peer")])
    assert SENTINEL_DIGITS not in _digits(repr(sim)) and SENTINEL_DIGITS not in _digits(repr(Ring(SENTINEL_DIGITS)))


# ══ 3. 통화 명세 · 받는 통화 · backend_for · import 규칙 ═══════════════════════════════════════════════


def test_call_spec_has_the_plan_fields_and_is_frozen():
    spec = _spec()
    assert list(spec.__dataclass_fields__) == ["direction", "to_number", "from_number", "language", "voice_id",
                                               "first_line", "instructions", "tools", "max_seconds", "record_to"]
    with pytest.raises(FrozenInstanceError):
        spec.to_number = STAFF_NUMBER
    assert isinstance(_spec(tools=list(TOOLS)).tools, tuple)  # 목록으로 줘도 고정된 꼴로
    assert _spec(tools=()).tools == ()
    assert _spec(record_to=Path("recordings/1/2")).record_to == Path("recordings/1/2")
    assert _spec(voice_id=None).voice_id is None and _spec("in").to_number is None


def test_call_spec_and_incoming_never_print_numbers():
    spec = _spec()
    incoming = Incoming(caller_number=SENTINEL_DIGITS, to_number=OUR_NUMBER, at=datetime(2026, 11, 23, 1, tzinfo=UTC))
    for text in (repr(spec), str(spec), repr(incoming), str(incoming), f"{[spec, incoming]}"):
        assert SENTINEL_DIGITS not in _digits(text) and OUR_NUMBER not in _digits(text)
    assert "direction='out'" in repr(spec) and "Incoming(" in repr(incoming)


@pytest.mark.parametrize("field", ["first_line", "instructions"])
@pytest.mark.parametrize("number", [SENTINEL_PHONE, "010 0000 0199", "01000000199", "+82 10-0000-0199",
                                    "공일공 공공공공 공일구구", "0 1 0 0 0 0 0 0 1 9 9", "070-0000-0100",
                                    "02-345-6789", "1588-0199"])
def test_call_spec_refuses_text_with_a_phone_number(field, number):
    """번호가 든 글은 음성 모델에게 갈 수 없다 — 만들 때 막는다(오류 글에 그 글을 싣지 않는다)."""
    good = _spec()
    with pytest.raises(ValueError) as caught:
        replace(good, **{field: f"{getattr(good, field)} 회신 번호는 {number} 입니다"})
    assert not _digits(str(caught.value)) and "회신" not in str(caught.value)


def test_call_spec_refuses_its_own_numbers_in_any_spacing():
    with pytest.raises(ValueError):
        _spec(instructions="상대 번호: 0-1-0-0-0-0-0-0-1-9-9")
    with pytest.raises(ValueError):
        _spec(to_number="0212345678", instructions="상대는 02) 1234 - 5678 로 받는다")
    with pytest.raises(ValueError):
        _spec("in", first_line="우리 번호 0 7 0 / 0 0 0 0 / 0 1 0 0 으로 주세요")


@pytest.mark.parametrize("text", ["2026-11-23 08:00 에 타설", "A동 1203호 · 3층 12구간", "작업 12·13·14 를 묻는다",
                                  "가린 번호 [번호] 는 그대로 둔다", "근무 08:00~18:00, 3일 뒤 11월 26일"])
def test_call_spec_accepts_dates_rooms_and_masked_numbers(text):
    assert _spec(instructions=text).instructions == text


@pytest.mark.parametrize("over", [
    {"direction": "both"}, {"to_number": None}, {"to_number": ""}, {"from_number": ""}, {"from_number": None},
    {"language": ""}, {"voice_id": ""}, {"first_line": ""}, {"first_line": "   "}, {"max_seconds": 0},
    {"max_seconds": -5}, {"max_seconds": 60.5}, {"max_seconds": True}, {"tools": (TOOLS[0], TOOLS[0])},
    {"tools": ({"name": "record_answer"},)}, {"record_to": "recordings/1/2"}, {"instructions": None},
    {"instructions": ""}, {"instructions": "  \n"}, {"to_number": 1000000199},
])
def test_call_spec_checks_its_values(over):
    with pytest.raises(ValueError) as caught:
        _spec(**over)
    assert SENTINEL_DIGITS[1:] not in _digits(str(caught.value))


def test_inbound_spec_has_no_number_to_dial():
    with pytest.raises(ValueError):
        _spec("in", to_number=SENTINEL_DIGITS)
    assert _spec("in").direction == "in"


def test_tool_definition_is_the_harness_one_not_a_copy():
    assert voice_session.ToolDef is ToolDef
    for path in VOICE.glob("*.py"):
        classes = {n.name for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(n, ast.ClassDef)}
        assert "ToolDef" not in classes, path.name


def test_incoming_needs_a_time_zone_and_voice_info_a_known_gender():
    with pytest.raises(ValueError):
        Incoming(caller_number=None, to_number=OUR_NUMBER, at=datetime(2026, 11, 23, 10, 0))
    with pytest.raises(ValueError):
        Incoming(caller_number="", to_number=OUR_NUMBER, at=datetime(2026, 11, 23, 10, tzinfo=UTC))  # 없으면 None
    ok = Incoming(caller_number=None, to_number=OUR_NUMBER, at=datetime(2026, 11, 23, 10, tzinfo=UTC))
    assert ok.caller_number is None
    assert get_args(VoiceInfo.__annotations__["gender"]) == ("male", "female", "unknown")
    for bad in ({"gender": "other"}, {"id": ""}, {"name": ""}):
        with pytest.raises(ValueError):
            VoiceInfo(**({"id": "sim-x", "name": "가상", "gender": "male"} | bad))


def test_backend_for_is_not_ready_until_a_backend_exists():
    """SDK 어댑터(Task 113)가 붙기 전에는 고를 백엔드가 없다 — 아무것도 걸지 않고 NotReady."""
    with pytest.raises(NotReady) as caught:
        voice_session.backend_for(None)
    assert "준비" in str(caught.value)


def test_pinned_backend_is_what_backend_for_returns():
    outer, inner = SimulatedVoice([]), SimulatedVoice([])
    with voice_session.pinned(outer):
        assert voice_session.backend_for(None) is outer
        with voice_session.pinned(inner):
            assert voice_session.backend_for(None) is inner
        assert voice_session.backend_for(None) is outer
    with pytest.raises(NotReady):
        voice_session.backend_for(None)
    with pytest.raises(RuntimeError), voice_session.pinned(outer):
        raise RuntimeError("시험 안에서 난 오류")
    with pytest.raises(NotReady):  # 오류로 나가도 걷힌다
        voice_session.backend_for(None)


def _pin_in_fresh_process(extra_env: dict[str, str]) -> str:
    code = textwrap.dedent("""
        import sys
        from app.outreach.voice import session
        from app.outreach.voice.simulated import SimulatedVoice
        assert "pytest" not in sys.modules
        try:
            with session.pinned(SimulatedVoice([])):
                print("ALLOWED")
        except RuntimeError as exc:
            print("REFUSED", exc)
    """)
    env = {k: v for k, v in os.environ.items() if k != registry.SANDBOX_ENV} | extra_env
    done = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60,
                          check=False)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_pinning_a_fake_backend_needs_pytest_or_the_sandbox_flag():
    """서버 프로세스에서 가짜 통화를 끼우면 진짜 예약 통화가 가짜로 가서 「통화됨」으로 적힌다 — 통로 등록부와 같은 규칙."""
    assert _pin_in_fresh_process({}).startswith("REFUSED")
    assert _pin_in_fresh_process({registry.SANDBOX_ENV: "0"}).startswith("REFUSED")
    assert _pin_in_fresh_process({registry.SANDBOX_ENV: "1"}) == "ALLOWED"


# 이 꾸러미의 파일은 음성 SDK(import 이름 clawops, 배포 이름 koreaaitel)·모델 SDK·HTTP 를 import 하지 않는다 — 함수 안에서도.
# SDK 를 import 하는 것은 kat_sdk.py 하나뿐이고(Task 113 — 그것도 함수 안에서만) 아래 훑기에서 그 파일만 뺀다.
SDK_NAMES = ("clawops", "koreaaitel", "google.genai", "openai", "aiohttp", "httpx", "livekit")
# 올라와 있는지 보는 것에서는 httpx 를 뺀다 — 번호 가리기(redact → app.info.generic)가 이미 불러온다. 직접 import 는 위에서 막는다.
SDK_LOADED = tuple(name for name in SDK_NAMES if name != "httpx")
SDK_ADAPTER = "kat_sdk.py"
TASK_FILES = ("__init__.py", "session.py", "simulated.py", "greeting.py", "voices.py")
DYNAMIC = "<동적 import>"


def _imported(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert not node.level, f"{path.name}: 상대 import 는 쓰지 않는다"
            names.add(node.module or "")
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call):
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if called in ("import_module", "__import__"):
                arg = node.args[0] if node.args else None
                names.add(arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else DYNAMIC)
    return names


def test_voice_modules_do_not_import_the_sdk_anywhere():
    files = sorted(VOICE.glob("*.py"))
    assert set(TASK_FILES) <= {f.name for f in files}
    for path in files:
        if path.name == SDK_ADAPTER:
            continue
        names = _imported(path)
        bad = {n for n in names for s in SDK_NAMES if n == s or n.startswith(s + ".")}
        assert not bad and DYNAMIC not in names, path.name


def test_interface_and_simulation_import_only_the_harness_words():
    """인터페이스·가짜·첫마디·음성 고르기는 app 안에서 하네스 낱말(types)·등록부의 모래상자 이름·번호 가리기만 쓴다 —
    DB·제공사·통로·모델을 끌어오지 않는다(의존은 음성 → 하네스 한쪽으로만)."""
    packages = {"app.outreach", "app.outreach.harness", "app.outreach.voice"}
    modules = ("app.outreach.harness.types", "app.outreach.harness.registry", "app.outreach.redact",
               "app.outreach.voice.session")
    for name in TASK_FILES:
        # backend_for(session.py) 만 SDK 어댑터를 부른다(Task 113 — 함수 안에서, 어댑터가 설정을 읽는다)
        allowed = (*modules, "app.outreach.voice.kat_sdk") if name == "session.py" else modules
        mine = {n for n in _imported(VOICE / name) if n == "app" or n.startswith("app.")}
        strangers = {n for n in mine if n not in packages and not any(n == m or n.startswith(m + ".") for m in allowed)}
        assert not strangers, (name, sorted(strangers))


def test_importing_the_voice_package_loads_no_sdk():
    """간접 import 까지: 새 프로세스에서 이 작업의 모듈을 모두 불러온 뒤에도 음성 SDK·모델 SDK 가 올라와 있지 않다."""
    wanted = [f"app.outreach.voice.{n[:-3]}" for n in TASK_FILES if n != "__init__.py"]
    code = textwrap.dedent(f"""
        import importlib, sys
        import app.outreach.voice
        for name in {wanted!r}:
            importlib.import_module(name)
        bad = {SDK_LOADED!r}
        print("LOADED", sorted(n for n in sys.modules if any(n == b or n.startswith(b + ".") for b in bad)))
    """)
    done = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=60,
                          check=False)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "LOADED []"


def test_no_app_module_pins_a_fake_voice_backend():
    """app/ 아래 코드는 가짜 통화를 끼우지 않는다(끼우는 것은 시험과, 등록부가 이름을 아는 모래상자 실행기뿐)."""
    offenders = []
    for path in sorted((BACKEND / "app").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if path == VOICE / "session.py" or "pinned" not in source or "voice" not in source:
            continue
        module = ".".join(path.relative_to(BACKEND).with_suffix("").parts)
        names = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom):
                names.add(node.module or "")
                names.update(f"{node.module}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
        uses_session = any(n == "app.outreach.voice.session" or n.startswith("app.outreach.voice.session.")
                           for n in names)
        calls_pinned = any(
            isinstance(node, ast.Call) and (
                (isinstance(node.func, ast.Attribute) and node.func.attr == "pinned"
                 and not (isinstance(node.func.value, ast.Name) and node.func.value.id == "registry"))
                or (isinstance(node.func, ast.Name) and node.func.id == "pinned"))
            for node in ast.walk(ast.parse(source)))
        if uses_session and calls_pinned and module not in registry.SANDBOX_MODULES:
            offenders.append(module)
    assert offenders == []


# ── 어댑터가 물려받는 법(Task 113) ──────────────────────────────────────────────────────────────────────
# from tests.outreach.voice.test_simulated import VoiceBackendContract
#
# class TestKatVoiceKeepsTheContract(VoiceBackendContract):
#     SCRIPTED_CLOCK = False            # 가짜 SDK 가 시계까지 대본대로 밀 수 있으면 True
#     def make(self, script, **options): ...   # 가짜 SDK 객체가 simulated.segments(script) 를 SDK 이벤트로 흘리는 KatVoice
#     def said(self, backend): ...             # 가짜 SDK 가 받은 「이 말을 하라」
#     def tool_returns(self, backend): ...     # 가짜 SDK 의 도구 함수가 돌려받은 값(JSON 을 풀어서)
#     def dialed(self, backend): ...           # 가짜 SDK 의 agent.call 이 받은 번호
#     def transferred_to(self, backend): ...   # 가짜 SDK 의 call.transfer 가 받은 번호
#     def rejected(self, backend): ...         # 가짜 SDK 의 IncomingCall.reject 가 불린 수
