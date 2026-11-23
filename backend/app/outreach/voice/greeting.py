"""통화 첫마디(Task 87): 코드가 고정 틀로 짓는다 — AI 임과 기록됨을 늘 밝히고, 번호나 모델이 쓴 글이 들어갈 자리가 없다.

- 들어가는 것은 현장 이름과 사람 이름뿐이다. 이름 칸에 번호가 적혀 있으면 번호만 빼고, 줄 바꿈·제어 글자·보이지 않는 글자는
  빈칸으로 바꾼다(숫자 사이에 낀 것은 빼서 붙인다 — 번호를 쪼개 숨기지 못하게). 번호를 빼고 남는 것이 없으면 거는 통화는
  ValueError(받은 값은 싣지 않는다), 받는 통화는 현장 이름 없는 문장. 번호 찾기는 redact.hide_phones 이고 그 한계를 물려받는다
  (사람이 일부러 띄어 적은 드문 꼴) — 이름 칸에 번호를 적지 않는 것이 첫째 줄이다.
- 없는 언어는 한국어(DEFAULT_LANGUAGE). 다른 언어는 Task 100 이 네 표(FIRST_LINES·INBOUND_LINES·INBOUND_LINES_NO_SITE·
  MUST_SAY)를 함께 채운다 — 틀에는 숫자를 쓰지 않는다.
- discloses(language, spoken) — 음성 모델이 **실제로 한** 말(받아쓰기)에 AI 임과 기록됨이 들어 있는가. SDK 에는 「이 문장을 그대로
  말하라」가 없어 첫마디를 모델이 말하므로, 통화 일꾼이 통화의 첫 발화(session 의 약속 2)를 이것으로 보고, 뒤 확인도 쓴다.
"""

import re
import unicodedata

from app.outreach import redact

DEFAULT_LANGUAGE = "ko"
FIRST_LINES = {
    "ko": "안녕하세요, {site} 일정 담당 ChronOS AI 비서입니다. 이 통화는 기록됩니다. {name}님 맞으신가요?",
}
INBOUND_LINES = {
    "ko": "안녕하세요, {site} 일정 담당 ChronOS AI 비서입니다. 이 통화는 기록됩니다. 무엇을 도와드릴까요?",
}
INBOUND_LINES_NO_SITE = {
    "ko": "안녕하세요, 일정 담당 ChronOS AI 비서입니다. 이 통화는 기록됩니다. 무엇을 도와드릴까요?",
}
# 꼭 하는 말: 묶음마다 하나는 들어 있어야 한다(빈칸을 빼고 소문자로 견준다 — 받아쓰기는 띄어쓰기·표기가 흔들린다).
MUST_SAY = {
    "ko": (("ai", "에이아이", "인공지능"), ("기록", "녹음")),
}
_SPACE_LIKE = frozenset({"Cc", "Cf", "Zl", "Zp"})  # 제어·보이지 않는 글자·줄 나눔
_HIDDEN = "\x00"  # 제어·보이지 않는 글자를 잠깐 바꿔 두는 표
_BETWEEN_DIGITS = re.compile(rf"(?<=[0-9０-９]){_HIDDEN}+(?=[0-9０-９])")
_EMPTY_BRACKETS = re.compile(r"[(（\[]\s*[)）\]]")  # 번호를 빼고 남은 빈 괄호


def _language(language: object) -> str:
    code = language.strip().lower() if isinstance(language, str) else ""
    return code if code in FIRST_LINES else DEFAULT_LANGUAGE


def _clean(name: object) -> str:
    """이름 칸에서 번호·제어 글자를 뺀 글(없으면 빈 글)."""
    if not isinstance(name, str):
        return ""
    text = "".join(_HIDDEN if unicodedata.category(char) in _SPACE_LIKE else char for char in name)
    text = _BETWEEN_DIGITS.sub("", text).replace(_HIDDEN, " ")  # 숫자 사이에 낀 것은 붙인다(쪼갠 번호가 다시 이어지게)
    text = redact.hide_phones(text).replace(redact.PHONE_MASK, " ")
    return " ".join(_EMPTY_BRACKETS.sub(" ", text).split())


def first_line(language: str, site: str, name: str) -> str:
    """거는 통화의 첫마디. 현장 이름이나 사람 이름이 비었으면(번호뿐이어도) ValueError."""
    site_name, person = _clean(site), _clean(name)
    if not site_name or not person:
        raise ValueError("첫마디에 넣을 현장 이름과 사람 이름이 있어야 합니다")
    return FIRST_LINES[_language(language)].format(site=site_name, name=person)


def inbound_line(language: str, site: str | None) -> str:
    """받는 통화의 첫마디. 현장이 정해지지 않았으면 현장 이름 없이."""
    code, site_name = _language(language), _clean(site)
    return INBOUND_LINES[code].format(site=site_name) if site_name else INBOUND_LINES_NO_SITE[code]


def discloses(language: str, spoken: str) -> bool:
    """실제로 한 말에 그 언어의 「꼭 하는 말」(AI 임 · 기록됨)이 모두 들어 있는가. 모르는 언어는 한국어 기준."""
    heard = "".join(spoken.split()).lower() if isinstance(spoken, str) else ""
    return all(any(word in heard for word in group) for group in MUST_SAY[_language(language)])
