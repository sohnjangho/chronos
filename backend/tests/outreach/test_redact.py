"""번호 가리기·키 지우기·로그 거르개(Task 62). 번호·키는 모두 가상이다."""

import importlib
import logging
import random
import time
from urllib.parse import quote, quote_plus

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text as sql
from sqlalchemy.exc import IntegrityError

from app.info.generic import key_survives
from app.main import app
from app.notify import diagnostics
from app.outreach import redact
from app.outreach.redact import (
    PHONE_MASK,
    HideSecrets,
    activate,
    add_secrets,
    forget_secrets,
    hide_phones,
    install,
    scrub,
    secrets,
)
from tests.outreach_doubles import SENTINEL_KEY, SENTINEL_PHONE, assert_clean

ACCOUNT = "AC00000000003c4d"
ZW = "\u200b"

# 문장 가운데에 넣으면 그 자리가 [번호] 하나로 바뀌어야 하는 꼴
PHONE_FORMS = [
    # 줄표·빈칸·점·괄호
    "010-0000-0199", "010 0000 0199", "010.0000.0199", "01000000199", "010 - 0000 - 0199", "(010) 0000-0199",
    "010–0000–0199", "010 0000-0199", "0100000-0199", "011-000-0199",
    # 그 밖의 구분: / ／ · ・ _ ~ 와 %인코딩(%20 %2D %2E %2B)
    "010/0000/0199", "010／0000／0199", "010·0000·0199", "010・0000・0199", "010_0000_0199", "010~0000~0199",
    "010%2D0000%2D0199", "010%200000%200199", "010%2E0000%2E0199", "%2B82%2010%200000%200199", "%2b82-10-0000-0199",
    # 폭 없는 글자(U+200B~D·U+2060·U+FEFF·U+00AD)
    f"010{ZW}0000{ZW}0199", "010\u200d0000\u200d0199", "010\u00ad0000\u00ad0199", "0\u206010-0000-0199",
    "\ufeff010-0000-0199", f"01{ZW}0-00{ZW}00-0199",
    # 휴대전화 11자리는 묶음을 어떻게 나눠도
    "010-00-00-0199", "010 0000 01 99", "010 00 00 01 99", "010/00/00/01/99", "010·0000·01·99",
    # +82·82·0082
    "+82 10-0000-0199", "+82-10-0000-0199", "+821000000199", "+82 (0)10-0000-0199", "+82 010 0000 0199",
    "82-10-0000-0199", "821000000199", "0082-10-0000-0199", "+82 2-2000-0199",
    # 0xx 지역(국번 2~9)·070·그 밖의 0 으로 시작하는 번호
    "02-200-0199", "02-2000-0199", "(02) 2000-0199", "0220000199", "031-200-0199", "064-2000-0199", "051.900.0199",
    "070-0000-0199", "070 0000 0199", "07000000199", "080-000-0199", "060-000-0199", "0505-000-0199",
    "050712340199",
    # 전각 숫자·기호·빈칸
    "０１０－００００－０１９９", "".join(chr(0xFF10 + int(c)) for c in "01000000199"), "＋８２ １０ ００００ ０１９９",
    "010　0000　0199",
    # 줄이 바뀐 곳에서 나뉨(묶음 사이·묶음 가운데·들여쓰기)
    "010-0000-\n0199", "010-\n0000-0199", "010-0000-\r\n    0199", "010 0000\n0199", "010-00\n00-0199",
    "0100000\n0199", "010-0000-01\n99", "02-20\n00-0199",
    # 한 자씩 띄움
    "0 1 0 0 0 0 0 0 1 9 9",
    # 나라 밖 번호(+ 가 붙은 꼴)
    "+1 212 000 0199", "+84 90 000 0199",
    # 한글로 읽은 숫자
    "공일공 공공공공 공일구구", "공일공-공공공공-공일구구", "공일공공공공공공일구구", "영일영 공공공공 공일구구",
    "공일공, 공공공공, 공일구구", "공 일 공 공 공 공 공 공 일 구 구", "공이 이공공 공일구구", "공일공\n공공공공 공일구구",
    "공일공 0000 0199", "010 공공공공 0199",
    # 소리 내어 읽을 때 줄표 자리(에·하고·다시)
    "공일공에 공공공공에 공일구구", "공일공에공공공공에공일구구", "영일영에 공공공공에 공일구구", "010에 0000에 0199",
    "공이에 이공공에 공일구구", "공일공 하고 공공공공 하고 공일구구", "공일공 다시 공공공공 다시 공일구구",
]


@pytest.mark.parametrize("form", PHONE_FORMS)
def test_hide_phones_forms_in_a_sentence(form):
    assert hide_phones(f"담당 번호는 {form} 입니다") == f"담당 번호는 {PHONE_MASK} 입니다"


def test_hide_phones_digits_and_spoken():
    assert "0199" not in hide_phones("번호는 010-0000-0199 입니다")
    assert "[번호]" in hide_phones("공일공 공공공공 공일구구 로 주세요")


@pytest.mark.parametrize(("text", "expected"), [
    ("010-0000-0199로 연락 주세요", "[번호]로 연락 주세요"),
    ("전화:01000000199입니다", "전화:[번호]입니다"),
    ("번호010-0000-0199번", "번호[번호]번"),
    ("010-0000-0199이에요", "[번호]이에요"),
    ("공일공 공공공공 공일구구 로 주세요", "[번호] 로 주세요"),
    ("공일공공공공공공일구구로 주세요", "[번호]로 주세요"),
    ("공일공 공공공공 공일구구이고요", "[번호]고요"),
    ("네 공일공에 공공공공에 공일구구요", "네 [번호]요"),
    ("뒷번호는 공공공공에 공일구구입니다", "뒷번호는 [번호]입니다"),  # 한글로 읽은 8자 — 조각이어도 지운다
    ("tel=+821000000199&x=1", "tel=[번호]&x=1"),
    ("to=%2B821000000199", "to=[번호]"),
    ("to=%2B82-10-0000-0199&b=1", "to=[번호]&b=1"),
    ("A1210-010-0000-0199", "A1210-[번호]"),
    ("3,010-0000-0199", "3,[번호]"),  # CSV 한 줄(순번,번호)
    ("(010-0000-0199)", "([번호])"),
    ("010-0000-0199, 02-200-0198", "[번호], [번호]"),
    ("010-0000-0199 010-0000-0198", "[번호] [번호]"),
    ("2026-11-24 010-0000-0199", "2026-11-24 [번호]"),
    ("010-0000-0199 2026-11-24 09:00", "[번호] 2026-11-24 09:00"),
    ("2026.11.24. 010-0000-0199", "2026.11.24. [번호]"),
    ("11월 24일 오전 9시 010-0000-0199 박현장", "11월 24일 오전 9시 [번호] 박현장"),
    ("A1210 철근 6명, 문의 070-0000-0199.", "A1210 철근 6명, 문의 [번호]."),
    (f"번호 010{ZW}0000{ZW}0199 끝", "번호 [번호] 끝"),  # 폭 없는 글자까지 같이 지운다
])
def test_hide_phones_inside_sentences(text, expected):
    assert hide_phones(text) == expected


@pytest.mark.parametrize("text", [
    "11월 24일 A1210 6명", "A1210", "A1210-A1220",
    # 날짜
    "2026-11-24", "2026.11.24", "2026. 11. 24.", "20261124", "2026/11/24", "2026-11-24 09:00~18:00",
    "2026-02-01, 2026-02-02", "2026-02-01\n2026-02-02", "2026-03-12, 2026-03-13", "02-01 ~ 02-12",
    "2026-01-12, 2026-01-13", "2026-01-12 2026-01-13 2026-01-14", "01/02 01/03", "01-02, 01-03, 01-04",
    "11/24-12/05", "11-24 ~ 12-05", "2026-11-24~12-05", "2026.11.24-2026.12.05", "1월 2일~1월 13일",
    "2026년 11월 24일 오전 9시", "26.02.01 ~ 26.03.31", "0102~0113", "0101-0131 공정",
    # 시각(앞에 지역 번호처럼 보이는 02·031 이 와도 — 국번은 0·1 로 시작하지 않는다)
    "09:00-18:00", "0800-1700", "야간 1800-2000 작업", "1800-2000", "1500~1800", "0900~1800",
    "02 0900-1800", "031 0900 1800", "02-01 0900-1800", "02 1200 1300", "공정 02 0730-1730", "팀 02 0800 1700",
    "3월 02일 0900~1800", "주간 07-19, 야간 19-07", "07:30 08:30 09:30 10:30",
    # 금액·수량
    "1,500,000원", "1,020,000,000원", "15,000,000원", "150000000원", "₩12,345,678", "3,010,000원", "1.020.000원",
    "합계 31,000,000원(부가세 3,100,000원)", "철근 0.5t, 12개, 300m", "₩1,234,567,890", "100,000 / 200,000",
    # 좌표
    "37.5665, 126.9780", "37.566535,126.977969", "좌표 (37.5665, 126.9780)",
    # 그 밖의 숫자
    "사업자 123-45-67890", "ID 120100000001995", "ID 0100000019", "A동 3층 302호 12명", "버전 1.2.3", "v0.10.0199",
    "층 02 03 04 05 06 07 08", "0 1 2 3 4 5 6 7 8 9", "점검 일정: 01 02 03 04 05 06",
    # 대표번호(자유 글에서는 남김 — 시각 범위와 모양이 같다)·짧은 조각
    "0507-1234-0199",  # 4-4-4 로 나뉜 050x 는 호실 목록과 모양이 같아 남긴다(붙여 쓰면 지운다)
    "대표번호 1588-0199", "1600-0199", "뒷자리 0199", "0000-0199", "010", "010-0000",
    # 숫자처럼 읽히는 한글 낱말
    "공사 일정은 이 일 정도", "공사 일이 삼일 이상 걸립니다", "일일 공사 일지", "시공사 오일 사이", "이삼일 공사",
    "구일 오후 이사", "공사 공정 일일 점검 사일 오일", "현장에 이사 오일", "3일에 2명", "공사 일이 삼일에 이사",
    "2026년 2월 1일에 02 회의", "공사 하고 이사 하고 오일", "삼사일 이내 공사",
    # 이미 가린 꼴
    "010-****-0199", "[번호]",
    # 날짜 목록·작은 수 목록·호실 목록(이 제품의 주된 자료 — 11자리 휴대전화 나눔 규칙에 걸리면 안 된다)
    "8/21~9/4, 10/15~11/2", "8/21 9/4 10/15 11/2", "8/21-9/4, 10/15-11/2", "1/8, 2/11, 5/5, 3/8, 11/27",
    "인원 0, 1, 15, 12, 10, 9, 11명", "0, 17, 3, 15, 19, 11, 7", "0502·0503·0504호", "0502/0503/0504호", "0502~0503~0504호",
    "0502_0503_0504호", "0502, 0503, 0504호 마감", "0502 0503 0504호", "1/8 2/11 5/5 3/8 11/27 7/18", "8/2, 1/15, 3/3, 8/21",
    "8/21·10/9·10/20·11/28·8/6·1/27", "0 18 19 1 19 14 9", "0/1/7/15/18/11/17", "0·11·2·8·10·13·11",
])
def test_hide_phones_keeps_dates_amounts_and_words(text):
    assert hide_phones(text) == text


def test_hide_phones_keeps_dates_and_ids():
    assert hide_phones("11월 24일 A1210 6명") == "11월 24일 A1210 6명"


@pytest.mark.parametrize("text", [
    "0 " * 20000, "0-" * 20000, "공 " * 20000, "공" * 40000, "010 공 " * 6666, "2026-02-01, " * 3600,
    "+0 " * 13333, "(0) " * 10000, "공에" * 20000, "8 " * 20000, "08-" * 13333, "+82 " * 10000,
    "0%20" * 10000, f"0{ZW}" * 20000, "0 1 " * 10000,
])
def test_hide_phones_is_fast_on_adversarial_text(text):
    """로그 거르개가 이벤트 루프를 붙잡지 않게 — 4만 자 안팎에서 50ms 쯤(시험은 여유를 둔 상한)."""
    started = time.perf_counter()
    out = hide_phones(text + " 끝. 010-0000-0199")
    assert time.perf_counter() - started < 0.2
    assert out.endswith(PHONE_MASK)


def test_scrub_removes_key_in_url():
    url = (f"POST https://api.example.invalid/v1/accounts/{ACCOUNT}/messages?key={SENTINEL_KEY}"
           f"&to={SENTINEL_PHONE}&to2=%2B821000000199")
    out = scrub(url, [SENTINEL_KEY, ACCOUNT])
    assert SENTINEL_KEY not in out and "3c4d" not in out and "0199" not in out
    assert out.startswith("POST https://api.example.invalid/v1/accounts/")


def test_scrub_removes_encoded_key_forms():
    key = "kat/test+key=ZZ9999"
    text = f"a={quote(key, safe='')} b={quote(quote(key, safe=''), safe='')} c={key.upper()}"
    out = scrub(text, [key])
    assert not key_survives(out, key)


def test_scrub_ignores_empty_secrets_and_still_hides_phones():
    assert scrub(f"to {SENTINEL_PHONE}", ["", ""]) == f"to {PHONE_MASK}"
    assert scrub("2026-11-24 6명", []) == "2026-11-24 6명"


def test_scrub_skips_short_and_odd_secrets_and_unwraps_secretstr():
    line = "account data saved at a path"
    assert scrub(line, ["a", "at", "1234567", None, 12345]) == line  # 8자보다 짧은 비밀은 글을 망가뜨린다
    assert SENTINEL_KEY not in scrub(f"k={SENTINEL_KEY}", [SecretStr(SENTINEL_KEY)])


def test_scrub_key_that_contains_digits_of_a_number():
    secret = "01000000199-secret"
    out = scrub(f"key={secret} to={SENTINEL_PHONE}", [secret])
    assert "0199" not in out and "secret" not in out


def test_diagnostics_scrub_uses_the_same_rules():
    """연결 진단의 지우기도 이 모듈을 거친다(구분·폭 없는 글자 꼴까지)."""
    for text in ("to 010~0000~0199", f"to 010{ZW}0000{ZW}0199", "to 공일공 공공공공 공일구구", f"k={SENTINEL_KEY.upper()}"):
        out = diagnostics.scrub(text, secrets=[SENTINEL_KEY], numbers=[])
        assert "0199" not in out and "구구" not in out and not key_survives(out, SENTINEL_KEY)


# ── 로그 거르개 ─────────────────────────────────────────────────────────────


@pytest.fixture
def keys(monkeypatch):
    """로그 거르개가 지울 비밀 목록(시험이 끝나면 원래 거르개로 돌아간다)."""
    monkeypatch.setattr(redact, "_FILTER", redact._FILTER)
    install(lambda: [SENTINEL_KEY, ACCOUNT])


@pytest.fixture
def factory():
    """시험이 바꾼 LogRecord factory 를 되돌린다."""
    before = logging.getLogRecordFactory()
    yield
    logging.setLogRecordFactory(before)
    activate()


def test_log_filter(caplog, keys):
    logging.getLogger("app.outreach").warning("to %s", SENTINEL_PHONE)
    assert caplog.records and "0199" not in caplog.text
    assert_clean(caplog, ACCOUNT)


def test_log_filter_covers_child_loggers_made_later(caplog, keys):
    """거르개는 app.outreach 아래 모든 로거에 걸린다(로거 거르개는 자식에게 물려지지 않는다)."""
    logging.getLogger("app.outreach.harness.gate.t62_new_child").warning("to %s key=%s", SENTINEL_PHONE, SENTINEL_KEY)
    assert caplog.records
    assert_clean(caplog)


@pytest.mark.parametrize("name", ["app.errors", "uvicorn.error", "httpx", "app.programs.contacts.service"])
def test_log_filter_covers_error_and_http_loggers(caplog, keys, name):
    try:
        raise ValueError(f"(sqlite3.IntegrityError) [parameters: ('{SENTINEL_PHONE}', '{SENTINEL_KEY}')]")
    except ValueError:
        logging.getLogger(name).exception("처리하지 못한 오류: POST /api/x %s", ACCOUNT)
    assert caplog.records
    assert_clean(caplog, ACCOUNT)


def test_log_filter_covers_httpx_request_line(caplog, keys):
    caplog.set_level(logging.INFO, logger="httpx")
    logging.getLogger("httpx").info('HTTP Request: GET %s "HTTP/1.1 200 OK"',
                                    f"https://api.example.invalid/v1/accounts/{ACCOUNT}/messages?to=%2B821000000199")
    assert caplog.records
    assert_clean(caplog, ACCOUNT)


def test_log_filter_leaves_other_loggers(caplog, keys):
    logging.getLogger("app.t62_other").warning("seq %s", "2026-11-24")
    assert caplog.records[-1].getMessage() == "seq 2026-11-24"


def test_log_filter_cleans_exception_text(caplog, keys):
    try:
        try:
            raise KeyError(SENTINEL_PHONE)
        except KeyError as inner:
            raise ValueError(f"provider said {SENTINEL_PHONE} for {SENTINEL_KEY} at {ACCOUNT}") from inner
    except ValueError:
        logging.getLogger("app.outreach.t62").exception("보내기 실패")
    assert caplog.records
    assert "ValueError" in caplog.text and "보내기 실패" in caplog.text
    assert_clean(caplog, ACCOUNT)


def test_log_filter_cleans_stack_info(caplog, keys):
    logging.getLogger("app.outreach.t62").warning("s %s", SENTINEL_PHONE, stack_info=True)
    assert caplog.records
    assert_clean(caplog)


@pytest.mark.parametrize("sep", [", ", " ", "/", "·", "~", "_", " / ", "-", "."])
@pytest.mark.parametrize("pool", ["M/D", "small", "room", "HHMM"])
def test_lists_of_dates_numbers_and_rooms_are_never_changed(pool, sep):
    """무작위 목록(날짜 M/D·0~19·호실 4자리·시각 HHMM)을 구분마다 이어도 바뀌지 않는다."""
    values = {
        "M/D": [f"{m}/{d}" for m in range(1, 13) for d in range(1, 32)],
        "small": [str(i) for i in range(20)],
        "room": [f"{f:02d}{r:02d}" for f in range(1, 20) for r in range(1, 20)],
        "HHMM": [f"{h:02d}{m:02d}" for h in range(24) for m in (0, 30)],
    }[pool]
    rng = random.Random(f"{pool}{sep}")
    for _ in range(1500):
        text = sep.join(rng.choice(values) for _ in range(rng.randint(2, 8)))
        assert hide_phones(text) == text, text


@pytest.mark.parametrize(("text", "expected"), [
    ("공일공 일 공일공 공공공공 공일구구", "공일공 일 [번호]"),  # 고쳐 부른 받아쓰기 — 번호 전체를 덮는 쪽
    ("010 1 010 0000 0199", "010 1 [번호]"),
    ("공일공 일 공일공 일이삼사 오육칠팔", "공일공 일 [번호]"),
])
def test_corrected_dictation_masks_the_whole_number(text, expected):
    assert hide_phones(text) == expected


def test_log_filter_cleans_extra_fields_when_the_record_is_made(keys):
    """extra 칸은 줄을 만들 때 지운다 — getMessage 를 부르지 않고 __dict__ 를 바로 읽는 손잡이도 깨끗한 값을 본다."""
    seen = []

    class Raw(logging.Handler):
        def emit(self, record):
            seen.append(dict(record.__dict__))

    logger = logging.getLogger("app.outreach.t62.raw")
    handler = Raw()
    logger.addHandler(handler)
    try:
        logger.warning("sent", extra={"to": SENTINEL_PHONE, "deep": {"a": {"b": [SENTINEL_PHONE]}},
                                      "mixed": [{"c": (SENTINEL_KEY,)}], "obj": object()})
    finally:
        logger.removeHandler(handler)
    raw = seen[-1]
    assert "0199" not in raw["to"]
    assert "0199" not in raw["deep"]["a"]["b"][0] and SENTINEL_KEY not in raw["mixed"][0]["c"][0]  # 세 겹까지
    assert isinstance(raw["obj"], object)  # 글이 아닌 물건은 그대로 둔다


def test_log_filter_cleans_extra_fields(caplog, keys):
    logging.getLogger("app.outreach.t62").warning("sent", extra={
        "to": SENTINEL_PHONE, "body": f"key {SENTINEL_KEY}", "meta": {"to": SENTINEL_PHONE, "n": 3},
        "items": [SENTINEL_PHONE, 7], "pair": (SENTINEL_PHONE,)})
    record = caplog.records[-1]
    assert "0199" not in record.to and SENTINEL_KEY not in record.body
    assert "0199" not in record.meta["to"] and record.meta["n"] == 3
    assert "0199" not in record.items[0] and record.items[1] == 7 and "0199" not in record.pair[0]


def test_log_filter_hides_line_when_secrets_cannot_be_read(caplog, monkeypatch):
    monkeypatch.setattr(redact, "_FILTER", redact._FILTER)

    def broken() -> list[str]:
        raise RuntimeError("db down")

    install(broken)
    logging.getLogger("app.outreach.t62").warning("key=%s to=%s", SENTINEL_KEY, SENTINEL_PHONE)
    assert caplog.records and caplog.records[-1].getMessage() == redact.HIDDEN_LINE
    assert_clean(caplog)


@pytest.mark.parametrize("secrets", [
    [SecretStr(SENTINEL_KEY)], [SENTINEL_KEY, None, 12345], [SENTINEL_KEY, b"bytes-secret-123"],
])
def test_log_filter_takes_secretstr_and_ignores_odd_values(caplog, monkeypatch, secrets):
    monkeypatch.setattr(redact, "_FILTER", redact._FILTER)
    install(lambda: secrets)
    logging.getLogger("app.outreach.t62").warning("to %s key %s", SENTINEL_PHONE, SENTINEL_KEY)
    assert caplog.records
    assert_clean(caplog)


def test_log_filter_skips_short_secrets(caplog, monkeypatch):
    monkeypatch.setattr(redact, "_FILTER", redact._FILTER)
    install(lambda: ["a"])
    logging.getLogger("app.outreach.t62").warning("account data saved at a path")
    assert caplog.records[-1].getMessage() == "account data saved at a path"


def test_log_filter_never_raises_into_the_caller(caplog, monkeypatch):
    """거르는 도중 무엇이 터져도 로그를 남긴 코드로 올라가지 않고, 그 줄은 숨긴다."""
    monkeypatch.setattr(redact, "_FILTER", redact._FILTER)

    class Nasty:
        def get_secret_value(self):
            raise RuntimeError(f"boom {SENTINEL_PHONE}")

    install(lambda: [Nasty()])
    logging.getLogger("app.outreach.t62").warning("key=%s", SENTINEL_KEY)
    assert caplog.records and caplog.records[-1].getMessage() == redact.HIDDEN_LINE
    assert_clean(caplog)


def test_log_filter_survives_provider_that_logs(caplog, monkeypatch):
    monkeypatch.setattr(redact, "_FILTER", redact._FILTER)

    def chatty() -> list[str]:
        logging.getLogger("app.outreach.t62.provider").warning("비밀 목록을 읽음 %s", SENTINEL_PHONE)
        return [SENTINEL_KEY]

    install(chatty)
    logging.getLogger("app.outreach.t62").warning("key=%s", SENTINEL_KEY)
    assert len(caplog.records) == 2
    assert_clean(caplog)


def test_log_filter_bad_format_args_do_not_raise(caplog, keys):
    wrong = "two %s %s"  # 인자가 모자란 틀(일부러)
    logging.getLogger("app.outreach.t62").warning(wrong, SENTINEL_PHONE)
    assert caplog.records
    assert_clean(caplog)


def test_make_log_record_is_scrubbed_and_does_not_raise(keys):
    """QueueListener·소켓으로 받은 줄(logging.makeLogRecord — 이름이 나중에 붙음)."""
    late = logging.makeLogRecord({"name": "app.outreach.q", "msg": "to %s key %s", "args": (SENTINEL_PHONE, SENTINEL_KEY)})
    message = late.getMessage()
    assert "0199" not in message and SENTINEL_KEY not in message
    assert logging.makeLogRecord({}).getMessage() == ""
    other = logging.makeLogRecord({"name": "app.t62_other", "msg": "seq %s", "args": ("2026-11-24",)})
    assert other.getMessage() == "seq 2026-11-24"


def test_hide_secrets_as_plain_filter():
    record = logging.LogRecord("x", logging.WARNING, __file__, 1, "to %s key %s", (SENTINEL_PHONE, SENTINEL_KEY), None)
    assert HideSecrets(lambda: [SENTINEL_KEY]).filter(record)
    assert record.getMessage() == f"to {PHONE_MASK} key [키지움]"


def test_phone_filter_is_on_without_install(caplog):
    """app.outreach 를 불러오기만 해도 번호 지우기는 켜져 있다(키 목록은 install 이 준다)."""
    logging.getLogger("app.outreach.t62").warning("to %s", SENTINEL_PHONE)
    assert caplog.records and "0199" not in caplog.text


def _chain():
    """다른 라이브러리처럼 지금 factory 를 감싸는 factory."""
    inner = logging.getLogRecordFactory()

    def chain(*args, **kwargs):
        record = inner(*args, **kwargs)
        record.chained = True
        return record

    logging.setLogRecordFactory(chain)


@pytest.mark.parametrize("steps", [
    ["wrap", "activate"], ["activate", "wrap", "activate"], ["wrap", "activate", "reload"],
    ["activate", "wrap", "reload", "activate"],
])
def test_wrapping_factory_and_activate_never_recurse(caplog, factory, keys, steps):
    for step in steps:
        {"wrap": _chain, "activate": activate, "reload": lambda: importlib.reload(redact)}[step]()
    logging.getLogger("app.outreach.t62").warning("to %s key %s", SENTINEL_PHONE, SENTINEL_KEY)
    logging.getLogger("t62.plain").warning("plain")
    assert len(caplog.records) == 2 and caplog.records[0].chained
    assert_clean(caplog)


def test_activate_is_idempotent(factory):
    activate()
    activate()
    assert logging.getLogRecordFactory() is redact._make_record
    assert redact._BASE_FACTORY is not redact._make_record


def test_reload_does_not_wrap_itself_and_keeps_the_keys(caplog, factory, keys):
    importlib.reload(redact)  # 옛 판은 factory 를 자기 위에 다시 감아 RecursionError 가 났다
    assert logging.getLogRecordFactory() is redact._make_record
    assert redact._BASE_FACTORY is not redact._make_record
    logging.getLogger("app.outreach.t62").warning("to %s key %s", SENTINEL_PHONE, SENTINEL_KEY)
    assert caplog.records
    assert_clean(caplog)


def test_app_start_activates_the_filter(factory):
    """다른 코드가 factory 를 바꿔 끼워도 앱이 뜰 때 다시 건다(불러오는 순서에 기대지 않는다)."""
    logging.setLogRecordFactory(logging.LogRecord)
    with TestClient(app):
        assert logging.getLogRecordFactory() is redact._make_record


def test_db_errors_hide_bound_parameters(session):
    """제약 오류 글(로그·예외)에 묶인 값(번호)이 실리지 않는다 — create_engine(hide_parameters=True)."""
    insert = sql("INSERT INTO users (id, login_id, name, role, status, password_hash) "
                 "VALUES (1, :p, :p, 'user', 'active', 'x')")
    with pytest.raises(IntegrityError) as caught:
        session.execute(insert, {"p": SENTINEL_PHONE})
    session.rollback()
    assert "0199" not in str(caught.value)


# ── 비밀 등록(더하기만) ─────────────────────────────────────────────────────

KEY_A, KEY_B, KEY_C = "registered-key-AAAA1111", "installed-key-BBBB2222", "installed-key-CCCC3333"


@pytest.fixture
def source(monkeypatch):
    """install 원천을 바꾸는 시험 — 끝나면 원래 거르개로."""
    monkeypatch.setattr(redact, "_FILTER", redact._FILTER)


def test_add_secrets_survives_install(caplog, source):
    add_secrets(KEY_A)
    install(lambda: [KEY_B])
    logging.getLogger("app.outreach.t62").warning("a=%s b=%s", KEY_A, KEY_B)
    assert caplog.records
    assert_clean(caplog, KEY_A, KEY_B)
    assert set(secrets()) == {KEY_A, KEY_B}
    out = scrub(f"a={KEY_A} b={KEY_B}", secrets())
    assert not key_survives(out, KEY_A) and not key_survives(out, KEY_B)
    assert not key_survives(scrub(f"a={KEY_A}", []), KEY_A)  # 등록한 값은 scrub 이 늘 지운다


def test_second_install_drops_only_its_own_source(caplog, source):
    add_secrets(KEY_A)
    install(lambda: [KEY_B])
    install(lambda: [KEY_C])
    assert set(secrets()) == {KEY_A, KEY_C}
    logging.getLogger("app.outreach.t62").warning("a=%s c=%s", KEY_A, KEY_C)
    assert_clean(caplog, KEY_A, KEY_C)


def test_add_secrets_rules(source):
    install(list)  # 다른 시험이 남긴 원천과 상관없이
    add_secrets(SecretStr(KEY_A), KEY_A, "short", None, 12345, b"bytes-value-123")
    add_secrets()
    assert secrets() == (KEY_A,)


def test_registered_secrets_survive_activate_and_reload(caplog, factory, source):
    add_secrets(KEY_A)
    activate()
    importlib.reload(redact)
    assert KEY_A in redact.secrets()
    logging.getLogger("app.outreach.t62").warning("a=%s", KEY_A)
    assert_clean(caplog, KEY_A)


@pytest.mark.parametrize("name", ["httpx", "httpcore.http11"])
def test_registered_account_is_cleaned_from_http_logs(caplog, name):
    add_secrets(ACCOUNT)
    caplog.set_level(logging.DEBUG, logger=name)
    logging.getLogger(name).info('HTTP Request: GET https://api.example.invalid/v1/accounts/%s/messages "200"', ACCOUNT)
    assert caplog.records
    assert_clean(caplog, ACCOUNT)


def test_registered_values_are_added_to_a_plain_filter():
    add_secrets(KEY_A)
    record = logging.LogRecord("x", logging.WARNING, __file__, 1, "%s %s", (KEY_A, SENTINEL_KEY), None)
    HideSecrets(lambda: [SENTINEL_KEY]).filter(record)
    assert record.getMessage() == "[키지움] [키지움]"


def test_concurrent_add_secrets():
    import threading
    values = [f"concurrent-key-{n:04d}" for n in range(200)]
    threads = [threading.Thread(target=add_secrets, args=(v,)) for v in values]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert set(values) <= set(secrets())


def test_forget_secrets_is_reset_between_tests_part1():
    add_secrets(KEY_A)


def test_forget_secrets_is_reset_between_tests_part2():
    assert KEY_A not in secrets()
    add_secrets(KEY_A)
    forget_secrets()
    assert KEY_A not in secrets()


def test_diagnostics_scrub_removes_quote_plus_form_of_a_key():
    key = "kat test key ZZ9999"
    out = diagnostics.scrub(f"k={quote_plus(key)} raw={key}", secrets=[key], numbers=[])
    assert "kat+test+key" not in out and "ZZ9999" not in out
