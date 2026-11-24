"""연락처 언어(Task 100) — 주소록·문자·통화가 함께 쓰는 언어 표.

- SUPPORTED: 고를 수 있는 언어(코드 → 한국어 이름). 모르는 코드·꼴이 틀린 값은 한국어(DEFAULT)로 읽는다.
- CALLABLE: **AI 전화가 되는 언어** — 음성 진단 P10(둘째 언어 통화)이 실제로 통과한 언어만 넣는다(짐작하지 않는다).
  2026-11-24 아침 P10 이 영어(en)로 통과했다. 중국어·베트남어는 문자에는 쓰고, P10 이 그 언어로 통과하기 전까지 통화는
  한국어로 건다(call_language). 진단이 다른 언어로 통과하면 이 묶음에 더한다.
- line(code, verb): 모델 지시문(음성·글·초안 모두 같은 상수)에 넣는 「상대의 언어: en(영어). 영어로 말합니다/씁니다.」 한 줄.
  지시문 자체는 한국어로 쓴다.
- 문자(EUC-KR 로 실린다 — app.outreach.sms_text)로 쓸 언어(11-24 결정): 중국어 상대에게는 영어로(`text_language` — 중국어
  글자 대부분이 실리지 않는다), 베트남어 상대에게는 성조 없이(không dấu). 글 지시문·초안은 `text_line` 을 쓴다. 통화는 그대로.
- is_korean(text): 글의 글자 가운데 한글이 충분한가 — 받은 문자를 번역할지, 뒤 확인(한국어 규칙)을 믿을지 정할 때 쓴다.
- has_foreign_words(text): 한국어 글에 섞인 라틴 낱말(3자 이상, LATIN_OK 밖) — 「철근 배근 at 가상 물류센터 starts on November 30」처럼
  한글이 많아도 영어 날짜·말이 든 글을 뒤 확인이 한국어로 믿지 않게(고침 1). 2자(AI·OK·kg·mm)와 숫자가 붙은 코드(A1210·RC30·30MPa)는
  세지 않는다 — 다만 영어 달·요일 이름(줄임 포함)은 숫자가 붙어 있어도 센다(「Nov30」 — 고침 2).
"""

import re
import unicodedata

DEFAULT = "ko"
SUPPORTED: dict[str, str] = {"ko": "한국어", "en": "영어", "zh": "중국어", "vi": "베트남어"}
CALLABLE: frozenset[str] = frozenset({"ko", "en"})  # 진단 P10 통과(11-24: en). 통과한 언어만 더한다
SPEAK, WRITE = "말합니다", "씁니다"
LINE = "상대의 언어: {code}({name}). {name}로 {verb}."  # 넷 모두 「…어」로 끝나 「로」가 맞다


def _primary(value: object) -> str:
    """「en-US」「EN」「 vi 」 → 앞의 언어 코드(소문자). 글이 아니면 빈 글."""
    if not isinstance(value, str):
        return ""
    return value.strip().lower().replace("_", "-").split("-")[0]


def code(value: object) -> str:
    """고를 수 있는 언어의 코드. 모르는 값은 한국어."""
    primary = _primary(value)
    return primary if primary in SUPPORTED else DEFAULT


def name(value: object) -> str:
    return SUPPORTED[code(value)]


def callable(value: object) -> bool:  # 계획의 이름표(languages.callable) 그대로 — 내장 callable 을 이 모듈에서만 가린다
    """그 언어로 AI 전화를 걸 수 있는가(CALLABLE). 모르는 언어는 거짓."""
    return _primary(value) in CALLABLE


def call_language(value: object) -> str:
    """통화에 쓸 언어: 통화가 되는 언어면 그것, 아니면 한국어."""
    primary = _primary(value)
    return primary if primary in CALLABLE else DEFAULT


def line(value: object, verb: str) -> str:
    """지시문의 언어 한 줄(verb 는 SPEAK · WRITE)."""
    picked = code(value)
    return LINE.format(code=picked, name=SUPPORTED[picked], verb=verb)


TEXT_INSTEAD = {"zh": "en"}  # 문자로 쓸 언어가 연락처 언어와 다른 것
TEXT_NOTES = {
    "zh": "상대는 중국어를 쓰지만 문자에는 중국어 글자가 실리지 않아 영어로 씁니다.",
    "vi": "베트남어는 성조·발음 부호 없이 씁니다(예: Xin chao, ngay mai lam viec). 부호가 든 글자는 문자에 실리지 않습니다.",
}


def text_language(value: object) -> str:
    """문자·글 답에 쓸 언어: 중국어 상대는 영어, 그 밖은 연락처 언어(code)."""
    picked = code(value)
    return TEXT_INSTEAD.get(picked, picked)


def text_line(value: object) -> str:
    """글 지시문·초안의 언어 한 줄: line(text_language, WRITE) 에 그 언어의 문자 쓰기 안내를 붙인 것."""
    picked = code(value)
    note = TEXT_NOTES.get(picked)
    return line(text_language(picked), WRITE) + (f" {note}" if note else "")


def _hangul(char: str) -> bool:
    return "가" <= char <= "힣" or "ᄀ" <= char <= "ᇿ" or "㄰" <= char <= "㆏"


def is_korean(text: object) -> bool:
    """한글이 다른 글자의 절반 이상이면 한국어로 본다(글자가 없으면 참 — 옮길 것이 없다). 「네 OK」·「ChronOS AI 비서입니다」는
    한국어, 「OK」·한글 현장 이름이 든 영어 문장은 한국어가 아니다."""
    if not isinstance(text, str):
        return True
    letters = [char for char in unicodedata.normalize("NFC", text) if char.isalpha()]
    hangul = sum(1 for char in letters if _hangul(char))
    return 2 * hangul >= len(letters) - hangul


LATIN_OK: frozenset[str] = frozenset({"chronos", "mpa", "kgf", "ton", "tons", "rpm", "sms", "mms",
                                   "won", "usd", "krw"})  # 한국어 글에 써도 되는 3자+ 낱말(통화 낱말은 금액 검사가 읽는다)
_LATIN_WORD = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{3,}(?![A-Za-z0-9])")


# 영어 달·요일 이름과 줄임(숫자·서수가 붙어 있어도 — 「Nov30」「30Nov」「30thNov」「Sat.30」「Weds」, 고침 2·3)
_CALENDAR_WORD = re.compile(
    r"(?:(?<![A-Za-z])|(?<=\d(?:st|nd|rd|th)))(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?"
    r"|nov(?:ember)?|dec(?:ember)?|mon(?:day)?|tue(?:s(?:day)?)?|wed(?:s|nesday)?|thu(?:rs?(?:day)?)?|fri(?:day)?|sat(?:urday)?"
    r"|sun(?:day)?)(?![A-Za-z])", re.IGNORECASE)


def has_foreign_words(text: object) -> bool:
    """3자 이상 라틴 낱말이 LATIN_OK 밖에 하나라도 있거나, 영어 달·요일 이름이 숫자에 붙어서라도 있는가."""
    if not isinstance(text, str):
        return False
    plain = unicodedata.normalize("NFKC", text)
    return bool(_CALENDAR_WORD.search(plain)) or any(word.lower() not in LATIN_OK for word in _LATIN_WORD.findall(plain))
