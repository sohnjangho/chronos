"""연락처 언어(Task 100) — 주소록·문자·통화가 함께 쓰는 언어 표.

- SUPPORTED: 고를 수 있는 언어(코드 → 한국어 이름). 모르는 코드·꼴이 틀린 값은 한국어(DEFAULT)로 읽는다.
- CALLABLE: **AI 전화가 되는 언어** — 음성 진단 P10(둘째 언어 통화)이 실제로 통과한 언어만 넣는다(짐작하지 않는다).
  2026-11-24 아침 P10 이 영어(en)로 통과했다. 중국어·베트남어는 문자에는 쓰고, P10 이 그 언어로 통과하기 전까지 통화는
  한국어로 건다(call_language). 진단이 다른 언어로 통과하면 이 묶음에 더한다.
- line(code, verb): 모델 지시문(음성·글·초안 모두 같은 상수)에 넣는 「상대의 언어: en(영어). 영어로 말합니다/씁니다.」 한 줄.
  지시문 자체는 한국어로 쓴다.
- is_korean(text): 글의 글자 가운데 한글이 충분한가 — 받은 문자를 번역할지, 뒤 확인(한국어 규칙)을 믿을지 정할 때 쓴다.
- has_foreign_words(text): 한국어 글에 섞인 라틴 낱말(3자 이상, LATIN_OK 밖) — 「철근 배근 at 가상 물류센터 starts on November 30」처럼
  한글이 많아도 영어 날짜·말이 든 글을 뒤 확인이 한국어로 믿지 않게(고침 1). 2자(AI·OK·kg·mm)와 숫자가 붙은 코드(A1210·RC30·30MPa)는
  세지 않는다.
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


def has_foreign_words(text: object) -> bool:
    """3자 이상 라틴 낱말이 LATIN_OK 밖에 하나라도 있는가(영어 달·요일 이름 포함 — 모두 3자 이상이다)."""
    if not isinstance(text, str):
        return False
    return any(word.lower() not in LATIN_OK for word in _LATIN_WORD.findall(unicodedata.normalize("NFKC", text)))
