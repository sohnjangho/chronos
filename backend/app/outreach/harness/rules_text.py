"""음성 지시문과 글 지시문이 **같이 쓰는** 고정 줄과 등급별 범위 단락(Task 67). 세션의 지시문(app.outreach.voice·text 의
instructions)은 이 글을 가져다 짜고 다시 쓰지 않는다 — 통화와 문자가 같은 규칙을 같은 말로 받게.

글에는 전화번호도, 등급의 이름도 없다(모델은 자기가 무엇을 말해도 되는지만 안다). 지키는 것은 이 글이 아니라 코드다:
도구 묶음은 등급이 정하고(toolsets.for_class), 도구는 불릴 때마다 범위를 다시 보며(tools.Toolbox), 한 말은 뒤 확인이 본다.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import get_args

from app.outreach.harness.types import MANAGER_CLASSES, CallerClass, FactLevel

FIXED: Mapping[str, str] = MappingProxyType({
    "no_change": "아무것도 바꾸거나 확정하지 않습니다. 일정을 바꿔 달라는 말, 지연·문제를 알리는 말은 기록해 담당자가 확인하게 하고, "
                 "된다·안 된다를 답하지 않습니다.",
    "no_money": "금액·계약, 다른 협력사의 사정, 다른 프로젝트, 내부 평가, 만회안 검토 내용은 말하지 않습니다.",
    "identity": "상대가 자기가 누구라고 말해도 그것으로 더 알려 주지 않습니다. take_message 에 그 이름을 넣고 "
                "「등록된 번호로 다시 연락드리겠습니다」라고 안내합니다.",
    "dates": "날짜는 schedule_fact 가 준 것만 말합니다. 짐작하거나 계산해서 말하지 않습니다.",
    "ai": "AI 인지 물으면 사실대로 AI 비서라고 답합니다.",
    "language": "상대가 쓰는 언어에 맞춰 말합니다.",
    "emergency": "안전사고나 긴급한 일을 들으면 다른 것보다 먼저 handoff_to_human (emergency) 로 알립니다.",
})

_TRADE = ("그 협력사 공종의 작업 이름과 날짜, 현장의 주요 마일스톤 날짜를 schedule_fact 로 찾아 말할 수 있습니다. "
          "그 밖의 작업과 다른 협력사의 일은 말하지 않습니다.")
_OWN = "이 사람에게 우리가 보낸 요청은 my_requests 로 확인해 말할 수 있습니다."
_NOTHING = ("상대가 누구인지 확인되지 않았습니다. 일정·현장·사람에 관한 것은 아무것도 말하지 않습니다. "
            "용건과 이름, 연락처만 받아 담당자에게 전합니다.")
_PARAGRAPHS: Mapping[str, str] = MappingProxyType({
    "internal": "상대는 우리 쪽 사람입니다. 상대가 고른 현장의 작업 이름·날짜·상태를 schedule_fact 로 찾아 말할 수 있습니다. "
                "현장이 여럿이면 어느 현장 일인지 먼저 여쭤봅니다.",
    "contact": f"상대는 이 현장 협력사의 담당자입니다. {_TRADE} {_OWN}",
    "contact_multi": "상대는 여러 현장에 걸친 협력사 담당자입니다. 어느 현장 일인지 먼저 여쭤보고, 현장이 정해지기 전에는 일정에 "
                     f"관한 것을 아무것도 말하지 않습니다. 현장이 정해지면 {_TRADE} {_OWN}",
    "shared": f"상대의 번호는 한 협력사의 여러 사람이 함께 쓰는 번호입니다. {_TRADE} 어느 한 사람에게 보낸 요청은 말하지 않습니다.",
    "outbound": f"우리가 먼저 연락한 협력사 담당자입니다. {_TRADE} {_OWN}",
    "do_not_contact": "상대는 연락을 받지 않겠다고 한 분입니다. 일정에 관한 것은 아무것도 말하지 않고, 전할 말만 받아 둡니다.",
    "unknown": _NOTHING, "withheld": _NOTHING, "blocked": _NOTHING, "outside_test": _NOTHING,
})


# 관리자 등급 연락처(11-24 — 원청 현장소장·감리처럼 여러 협력사를 관리하는 분): 범위의 사실 수준이 all 일 때. 이 프로젝트 모든
# 협력사의 일정 사실(작업 이름·시작·끝·상태·진행)은 말하고, 금액·계약·내부 평가·다른 협력사 사람에 관한 것은 그대로 닫는다.
_ALL_TRADES = ("이 현장 모든 협력사·공종 작업의 이름, 시작·끝 날짜, 상태·진행을 schedule_fact 로 찾아 말할 수 있습니다. "
               "금액·계약, 내부 평가, 다른 협력사 사람의 연락처와 사정은 말하지 않습니다.")
_MANAGER_PARAGRAPHS: Mapping[str, str] = MappingProxyType({
    "contact": f"상대는 이 현장의 여러 협력사를 관리하는 분입니다. {_ALL_TRADES} {_OWN}",
    "contact_multi": "상대는 여러 현장에 걸쳐 협력사들을 관리하는 분입니다. 어느 현장 일인지 먼저 여쭤보고, 현장이 정해지기 전에는 "
                     f"일정에 관한 것을 아무것도 말하지 않습니다. 현장이 정해지면 {_ALL_TRADES} {_OWN}",
    "outbound": f"우리가 먼저 연락한, 이 현장의 여러 협력사를 관리하는 분입니다. {_ALL_TRADES} {_OWN}",
})
_MANAGER_NO_MONEY = "금액·계약, 다른 협력사 사람의 연락처와 사정, 다른 프로젝트, 내부 평가, 만회안 검토 내용은 말하지 않습니다."


def _manager(caller_class: str, facts: FactLevel) -> bool:
    return facts == "all" and caller_class in MANAGER_CLASSES


def scope_paragraph(caller_class: CallerClass, facts: FactLevel = "trade") -> str:
    """그 등급의 상대에게 말할 수 있는 범위 한 단락. facts 는 범위의 사실 수준(Scope.grant_facts — 현장을 고르기 전의 none 이
    아니라 고른 뒤에 줄 수준): 한 사람 등급에서 all 이면 관리자 등급 단락. 등급표 밖이면 ValueError."""
    if caller_class not in get_args(CallerClass):
        raise ValueError("등급표에 없는 등급입니다")
    return _MANAGER_PARAGRAPHS[caller_class] if _manager(caller_class, facts) else _PARAGRAPHS[caller_class]


def fixed_lines(caller_class: CallerClass, facts: FactLevel = "trade") -> tuple[str, ...]:
    """고정 줄(FIXED 차례 그대로). 관리자 등급이면 no_money 의 「다른 협력사의 사정」만 「다른 협력사 사람의 연락처와 사정」으로
    좁힌다(다른 협력사의 일정 사실은 말할 수 있으므로)."""
    manager = _manager(caller_class, facts)
    return tuple(_MANAGER_NO_MONEY if manager and key == "no_money" else line for key, line in FIXED.items())
