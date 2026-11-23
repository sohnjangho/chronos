"""전화번호 다루기: 정리(normalize)·휴대전화인가·가린 꼴(mask)·형식이 틀린 입력의 가린 꼴·묶음 손잡이(peer_key).

- 저장하는 꼴은 숫자만 남긴 국내 번호(`01000000199`). `+82`·`82`·`0082` 앞머리는 `0` 으로 바꾼다(`+82 (0)10…` 도).
- 받는 번호: 휴대전화(010 은 11자리, 011·016~019 는 10~11자리), 서울 02(9~10자리), 지역 031~064(10~11자리),
  인터넷 전화 070(11자리). 대표번호(15xx·16xx·18xx-xxxx)·080·060·050x(안심번호)는 사람에게 바로 닿는 번호가 아니고
  문자를 받지 못해 받지 않는다(설계 「하지 않는 것」: 050 안심번호). 나라 밖 번호도 받지 않는다.
- 전각 숫자·기호(NFKC)와 여러 줄표(‐‑‒–—−﹣)를 받는다. 숫자·빈칸·줄표·점·괄호·맨 앞 + 밖의 글자가 있으면 None
  (메모가 붙은 입력은 번호로 보지 않는다).
- 가린 꼴은 `010-****-0199`. 전체 번호를 보이는 곳은 reveal 한 곳뿐이다(Task 72).
"""

import hashlib
import hmac
import re
import unicodedata

from app.config import Settings

NO_NUMBER = "번호 없음"
_DASHES = str.maketrans(dict.fromkeys("‐‑‒–—−﹣", "-"))
_INPUT = re.compile(r"\+?[0-9\s\-.()]+")
_NOT_DIGIT = re.compile(r"[^0-9]")
# (앞자리, 가운데, 끝 4자리). 가린 꼴·번호 모양 판단(redact.hide_phones)이 같이 쓴다.
_PARTS = re.compile(r"(02|0(?:3[1-3]|4[1-4]|5[1-5]|6[1-4])|01[016789]|0[678]0|050[2-8])([0-9]{3,4})([0-9]{4})")
_FOUR_DIGIT_MIDDLE = ("010", "070")
_NOT_A_PERSON = ("050", "060", "080")  # 안심번호·정보 이용·수신자 부담 — 모양은 번호지만 저장하지 않는다
_PEER_SALT = b"chronos-peer:"


def _parts(digits: str) -> tuple[str, str, str] | None:
    """국내 번호(숫자만)를 (앞자리, 가운데, 끝 4자리)로. 번호 모양이 아니면 None."""
    m = _PARTS.fullmatch(digits)
    if m is None or (m.group(1) in _FOUR_DIGIT_MIDDLE and len(m.group(2)) != 4):
        return None
    return m.group(1), m.group(2), m.group(3)


def _local(digits: str) -> tuple[str, int]:
    """(국내 꼴 숫자, 떼어 낸 나라 앞머리 길이). `0082`·`82` 를 떼고 0 이 없으면 붙인다. 앞머리가 없으면 (그대로, 0)."""
    for prefix in ("0082", "82"):
        if digits.startswith(prefix):
            rest = digits[len(prefix):]
            return (rest if rest.startswith("0") else "0" + rest), len(prefix)
    return digits, 0


def normalize(raw: str | None) -> str | None:
    """숫자만 남긴 국내 꼴(`01000000199`). 받는 번호(모듈 머리 글)가 아니면 None."""
    if raw is None:
        return None
    text = unicodedata.normalize("NFKC", raw).translate(_DASHES).strip()
    if not _INPUT.fullmatch(text):
        return None
    digits = _NOT_DIGIT.sub("", text)
    if text.startswith("+") and not digits.startswith("82"):
        return None
    local, _ = _local(digits)
    parts = _parts(local)
    if parts is None or parts[0].startswith(_NOT_A_PERSON):
        return None
    return local


def is_mobile(number: str | None) -> bool:
    """휴대전화(01x) 번호인가. 정리 전 꼴도 받는다."""
    local = normalize(number)
    return local is not None and local.startswith("01")


def mask_bad(raw: str) -> str:
    """형식이 틀린 입력의 가린 꼴: 앞 3자리 + 「…」. 비었으면 「번호 없음」."""
    head = unicodedata.normalize("NFKC", raw).strip()[:3]
    return f"{head}…" if head else NO_NUMBER


def mask(number: str | None) -> str:
    """`010-****-0199`. None 이면 「번호 없음」, 번호가 아니면 mask_bad(전체를 되돌려 보이지 않는다)."""
    if number is None:
        return NO_NUMBER
    local = normalize(number)
    if local is None:
        return mask_bad(number)
    area, _, last = _parts(local)
    return f"{area}-****-{last}"


def peer_key(number: str) -> str:
    """Settings.secret_key 로 만든 HMAC-SHA256 앞 12자. 같은 번호의 여러 꼴은 같은 값, 번호로 되돌릴 수 없다."""
    value = normalize(number) or number.strip()
    digest = hmac.new(Settings().secret_key.encode(), _PEER_SALT + value.encode(), hashlib.sha256)
    return digest.hexdigest()[:12]
