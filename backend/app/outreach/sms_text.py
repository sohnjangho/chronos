"""문자로 나갈 글을 제공사가 실을 수 있는 글로(`sms_safe`)·실을 수 없으면 그 까닭(`problem`). 순수 함수 — 제공사 호출
(app.outreach.provider)·문자 통로·나가는 문(앞 확인·「같은 글」 견주기)·묶음 다시 보내기가 같이 쓴다(하네스가 provider 를
import 하지 않으므로 따로 둔다).

제공사는 문자를 EUC-KR(KS X 1001)로 세고 싣는다 — 그 밖의 글자(줄표 — 등)가 있으면 422 로 거절한다(2026-11-24 실측).
CP949 에만 있는 한글(똠·햏 등)도 KS X 1001 밖이다(파이썬 euc_kr 은 그것을 8바이트 조합 꼴로 바꾸므로 2바이트까지만 받는다).
**글자는 지우지 않는다**: 바꿀 수 있는 것은 비슷한 글자로 바꾸고, 지우는 것은 기호·꾸밈·빈칸 갈래(So·Sk·Cf·Zs·Cs — 그림
글자·폭 없는 글자 등)뿐이다. 그래도 실을 수 없는 글자(베트남어 성조·일부 한자 등)가 남으면 보내지 않는다(`problem`).
"""

import unicodedata

from app.outreach import languages

SMS_BYTES_MAX = 2000  # 긴 문자(LMS) 한 건의 EUC-KR 바이트 상한
NOT_CARRIED = "문자로 실을 수 없는 글자가 있습니다(예: 베트남어 성조, 일부 한자). 다른 표기로 고쳐 주세요."
AUTO_NOT_CARRIED = "자동 답에 문자로 실을 수 없는 글자가 있어 보내지 않았습니다."  # 자동 답은 사람이 고쳐 보내지 않는다
AUTO_TOO_LONG = "자동 답이 문자 한 건에 싣기에 너무 길어 보내지 않았습니다."
EMPTY = "보낼 글이 없습니다"
TOO_LONG = f"문자 한 건에 싣기에 글이 너무 깁니다(한글 {SMS_BYTES_MAX // 2}자 안으로 줄여 주세요)."
# 흔한 것은 비슷한 글자로(「…」·둥근 따옴표는 KS X 1001 에 있지만 1바이트 글자로)
SMS_SWAPS = str.maketrans({
    **dict.fromkeys("\u2014\u2013\u2015\u2012\u2010\u2011\u2212\ufe58\ufe63\uff0d", "-"),
    **dict.fromkeys("\u2018\u2019\u201a", "'"), **dict.fromkeys("\u201c\u201d\u201e", '"'), "\u2026": "...",
    "\u2022": "\u00b7",
    **dict.fromkeys("\u00a0\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f", " "),
})
_DROPPABLE = frozenset({"So", "Sk", "Cf", "Zs", "Cs"})  # 실을 수 없으면 빼도 되는 갈래(그림 글자·폭 없는 글자·빈칸)
# 표시 갈래(M)지만 그림 글자에만 붙는 것: 모양 고르개(U+FE00~FE0F·U+E0100~E01EF)와 키캡 테(U+20E3) — 그림 글자와 함께 뺀다
_EMOJI_MARKS = frozenset(map(chr, (*range(0xFE00, 0xFE10), *range(0xE0100, 0xE01F0), 0x20E3)))


def _size(ch: str) -> int | None:
    """그 글자의 EUC-KR 바이트(1 또는 2). KS X 1001 밖이면 None."""
    try:
        size = len(ch.encode("euc_kr"))
    except UnicodeEncodeError:
        return None
    return size if size <= 2 else None


def _without_tones(text: str) -> str:
    """베트남어 성조·발음 부호를 뺀 글(không dấu): đ/Đ → d/D, NFD 로 풀어 붙는 부호(Mn)를 뺀다. 한글은 풀어도 부호가 없어 그대로."""
    decomposed = unicodedata.normalize("NFD", text.replace("\u0111", "d").replace("\u0110", "D"))
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def sms_safe(text: str, language: object = None) -> str:
    """문자로 나갈 글 → (연락처 언어가 베트남어일 때만 성조를 빼고) NFC 로 맞추고 SMS_SWAPS 로 바꾼 뒤, KS X 1001 밖인
    기호·꾸밈·빈칸 갈래 글자만 뺀 글. 글자·숫자·표시(L·N·M 갈래)와 그 밖의 것은 남긴다 — 실을 수 있는지는 `problem` 이
    본다. 두 번 거쳐도 같다."""
    if languages.code(language) == "vi":
        text = _without_tones(text)
    swapped = unicodedata.normalize("NFC", text).translate(SMS_SWAPS)
    return "".join(ch for ch in swapped
                   if _size(ch) is not None or (ch not in _EMOJI_MARKS and unicodedata.category(ch) not in _DROPPABLE))


def problem(text: str, language: object = None) -> str | None:
    """sms_safe 를 거친 글을 문자로 보낼 수 없는 까닭(한국어) 또는 None: 비었다·실을 수 없는 글자가 남았다·너무 길다."""
    safe = sms_safe(text, language)
    if not safe.strip():
        return EMPTY
    sizes = [_size(ch) for ch in safe]
    if None in sizes:
        return NOT_CARRIED
    return TOO_LONG if sum(sizes) > SMS_BYTES_MAX else None


def byte_size(text: str) -> int:
    """sms_safe 를 거친 글의 EUC-KR 바이트(실을 수 없는 글자는 2로 센다 — 그런 글은 problem 이 막는다)."""
    return sum(_size(ch) or 2 for ch in sms_safe(text))
