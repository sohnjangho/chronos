"""전화번호 다루기: 정리(normalize)·종류(kind)·가능 채널(storable·can_sms·can_call)·가린 꼴·묶음 손잡이(peer_key).

- normalize 는 「어느 번호인가」의 열쇠다. 국내 번호면 종류와 상관없이 숫자만 남긴 한 꼴(`01000000199`)을 돌려준다.
  `+82`·`82`·`0082` 앞머리는 `0` 으로 바꾼다(`+82 (0)10…`·`(+82) 10…` 도). 같은 번호의 여러 꼴은 같은 열쇠가 되므로
  차단·찾기·peer_key 가 꼴에 따라 갈리지 않는다.
- 종류: 휴대전화 mobile(010 은 11자리, 011·016~019 는 10~11자리) · 지역 landline(02 9~10자리, 031~064 10~11자리 — 국번은
  2~9 로 시작) · 인터넷 internet(070, 11자리) · 대표번호 rep(15xx·16xx·18xx-xxxx, 8자리) · 안심번호 safe(0502~0508,
  11~12자리) · 수신자 부담 tollfree(080) · 정보 이용 premium(060).
- 무엇을 할 수 있는가는 여기 세 함수만 정한다(주소록 API·나가는 문은 규칙을 따로 두지 않는다): storable(060 밖 전부) ·
  can_sms(휴대전화만) · can_call(060 밖 전부).
- 전각 숫자·기호(NFKC), 여러 줄표(‐‑‒–—−﹣), 폭 없는 글자(U+200B~D·U+2060·U+FEFF·U+00AD)를 받는다. 숫자·빈칸·줄표·점·괄호·
  맨 앞 + 밖의 글자가 있으면 None(메모가 붙은 입력은 번호로 보지 않는다). 나라 밖 번호도 None.
- 가린 꼴은 `010-****-0199`(대표번호는 `1588-****`). 전체 번호를 보이는 곳은 reveal 한 곳뿐이다(Task 72).
"""

import hashlib
import hmac
import re
import unicodedata
from typing import Literal

from app.config import Settings

Kind = Literal["mobile", "landline", "internet", "rep", "safe", "tollfree", "premium"]

NO_NUMBER = "번호 없음"
FORMAT_CHARS = "\u200b\u200c\u200d\u2060\ufeff\u00ad"  # 폭 없는 글자 — 번호를 읽기 전에 뺀다
_CLEAN = str.maketrans({**dict.fromkeys("‐‑‒–—−﹣", "-"), **dict.fromkeys(FORMAT_CHARS)})
_INPUT = re.compile(r"\(?\s*(\+)?[0-9\s\-.()]+")
_NOT_DIGIT = re.compile(r"[^0-9]")
# 앞자리(지역·휴대전화·070·080·060·050x). redact.hide_phones 가 번호 길이를 가늠할 때도 쓴다.
AREA = re.compile(r"01[016789]|02|0(?:3[1-3]|4[1-4]|5[1-5]|6[1-4])|0[678]0|050[2-8]")
_REP = re.compile(r"1[568][0-9]{6}")
_FOUR_DIGIT_MIDDLE = ("010", "070")
_NOT_STORABLE = ("premium",)
_PEER_SALT = b"chronos-peer:"


def _area_kind(area: str) -> Kind:
    if area.startswith("01"):
        return "mobile"
    return {"070": "internet", "080": "tollfree", "060": "premium"}.get(area) or (
        "safe" if area.startswith("050") else "landline")


def _parts(digits: str, *, rep: bool = True) -> tuple[str, str, str] | None:
    """국내 번호(숫자만)를 (앞자리, 가운데, 끝 4자리)로. 대표번호는 (앞 4자리, "", 끝 4자리). 번호 모양이 아니면 None."""
    if rep and _REP.fullmatch(digits):
        return digits[:4], "", digits[4:]
    m = AREA.match(digits)
    if m is None:
        return None
    area = m.group()
    rest = digits[len(area):]
    if len(rest) not in (7, 8) or _NOT_DIGIT.search(rest):
        return None
    middle = rest[:-4]
    if area in _FOUR_DIGIT_MIDDLE and len(middle) != 4:
        return None
    if _area_kind(area) == "landline" and middle[0] in "01":  # 지역 번호의 국번은 0·1 로 시작하지 않는다
        return None
    return area, middle, rest[-4:]


def _local(digits: str) -> tuple[str, int]:
    """(국내 꼴 숫자, 떼어 낸 나라 앞머리 길이). `0082`·`82` 를 떼고 0 이 없으면 붙인다. 앞머리가 없으면 (그대로, 0)."""
    for prefix in ("0082", "82"):
        if digits.startswith(prefix):
            rest = digits[len(prefix):]
            return (rest if rest.startswith("0") else "0" + rest), len(prefix)
    return digits, 0


def normalize(raw: str | None) -> str | None:
    """숫자만 남긴 국내 꼴(`01000000199`). 국내 번호(모듈 머리 글의 일곱 종류)가 아니면 None."""
    if raw is None:
        return None
    text = unicodedata.normalize("NFKC", raw).translate(_CLEAN).strip()
    m = _INPUT.fullmatch(text)
    if m is None:
        return None
    digits = _NOT_DIGIT.sub("", text)
    if m.group(1) and not digits.startswith("82"):
        return None
    local, _ = _local(digits)
    return local if _parts(local) is not None else None


def kind(number: str | None) -> Kind | None:
    """번호의 종류. 정리 전 꼴도 받는다. 번호가 아니면 None."""
    local = normalize(number)
    if local is None:
        return None
    area, middle, _ = _parts(local)
    return "rep" if not middle else _area_kind(area)


def storable(number: str | None) -> bool:
    """주소록·차단 목록에 둘 수 있는가(정보 이용 060 밖 전부)."""
    found = kind(number)
    return found is not None and found not in _NOT_STORABLE


def can_sms(number: str | None) -> bool:
    """문자를 보낼 수 있는가(휴대전화만)."""
    return kind(number) == "mobile"


def can_call(number: str | None) -> bool:
    """전화를 걸 수 있는가(정보 이용 060 밖 전부)."""
    return storable(number)


def is_mobile(number: str | None) -> bool:
    """휴대전화(01x) 번호인가. 정리 전 꼴도 받는다."""
    return kind(number) == "mobile"


def mask_bad(raw: str) -> str:
    """형식이 틀린 입력의 가린 꼴: 앞 2글자까지(짧으면 반까지) + 「…」. 비었으면 「번호 없음」."""
    text = unicodedata.normalize("NFKC", raw).translate(_CLEAN).strip()
    if not text:
        return NO_NUMBER
    return f"{text[:min(2, len(text) // 2)]}…"


def mask(number: str | None) -> str:
    """`010-****-0199`(대표번호 `1588-****`). None 이면 「번호 없음」, 번호가 아니면 mask_bad(전체를 되돌려 보이지 않는다)."""
    if number is None:
        return NO_NUMBER
    local = normalize(number)
    if local is None:
        return mask_bad(number)
    area, middle, last = _parts(local)
    return f"{area}-****" if not middle else f"{area}-****-{last}"


def peer_key(number: str) -> str:
    """Settings.secret_key 로 만든 HMAC-SHA256 앞 12자. 같은 번호의 여러 꼴은 같은 값, 번호로 되돌릴 수 없다."""
    value = normalize(number) or number.strip()
    digest = hmac.new(Settings().secret_key.encode(), _PEER_SALT + value.encode(), hashlib.sha256)
    return digest.hexdigest()[:12]
