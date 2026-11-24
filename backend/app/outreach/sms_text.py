"""문자로 나갈 글을 제공사가 실을 수 있는 글로(`sms_safe`). 순수 함수 — 제공사 호출(app.outreach.provider)·문자 통로·
나가는 문(「같은 글」 견주기)이 같이 쓴다(하네스가 provider 를 import 하지 않으므로 따로 둔다)."""

# 문자는 제공사가 EUC-KR(CP949)로 세고 싣는다 — 그 밖의 글자(줄표 — 등)가 있으면 422 로 거절한다(2026-11-24 실측).
# 흔한 것은 비슷한 글자로 바꾸고(「…」·둥근 따옴표는 CP949 에 있지만 1바이트 글자로), 폭 없는 글자는 뺀다
SMS_SWAPS = str.maketrans({
    **dict.fromkeys("\u2014\u2013\u2015\u2012", "-"), **dict.fromkeys("\u2018\u2019\u201a", "'"),
    **dict.fromkeys("\u201c\u201d\u201e", '"'), "\u2026": "...",
    **dict.fromkeys("\u00a0\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f", " "),
    **dict.fromkeys("\u200b\u200c\u200d\u2060\ufeff\u180e"),
})


def _carried(ch: str) -> bool:
    try:
        ch.encode("cp949")
    except UnicodeEncodeError:
        return False
    return True


def sms_safe(text: str) -> str:
    """문자로 나갈 글 → 제공사가 실을 수 있는 글(늘 `encode("cp949")` 된다). SMS_SWAPS 로 바꾸고, 그래도 CP949 밖인
    글자(그림 글자·짝 없는 서로게이트 등)는 뺀다. 한글·KS X 1001 기호(· 「」 ※ ○)는 그대로. 두 번 거쳐도 같다."""
    return "".join(ch for ch in text.translate(SMS_SWAPS) if _carried(ch))
