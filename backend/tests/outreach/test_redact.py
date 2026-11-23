"""번호 가리기·키 지우기·로그 거르개(Task 62). 번호·키는 모두 가상이다."""

import logging
from urllib.parse import quote

import pytest

from app.info.generic import key_survives
from app.outreach import redact
from app.outreach.redact import PHONE_MASK, HideSecrets, hide_phones, install, scrub
from tests.outreach_doubles import SENTINEL_KEY, SENTINEL_PHONE, assert_clean

ACCOUNT = "AC00000000003c4d"

# 문장 가운데에 넣으면 그 자리가 [번호] 하나로 바뀌어야 하는 꼴
PHONE_FORMS = [
    # 줄표·빈칸·점·괄호
    "010-0000-0199", "010 0000 0199", "010.0000.0199", "01000000199", "010 - 0000 - 0199", "(010) 0000-0199",
    "010–0000–0199", "010 0000-0199", "0100000-0199", "011-000-0199",
    # +82·82·0082
    "+82 10-0000-0199", "+82-10-0000-0199", "+821000000199", "+82 (0)10-0000-0199", "+82 010 0000 0199",
    "82-10-0000-0199", "821000000199", "0082-10-0000-0199", "+82 2-0000-0199",
    # 0xx 지역·070·그 밖의 0 으로 시작하는 번호
    "02-000-0199", "02-0000-0199", "(02) 0000-0199", "0200000199", "031-000-0199", "064-0000-0199", "051.000.0199",
    "070-0000-0199", "070 0000 0199", "07000000199", "080-000-0199", "060-000-0199", "0505-000-0199",
    # 전각 숫자·기호·빈칸
    "０１０－００００－０１９９", "０１００００００１９９", "＋８２ １０ ００００ ０１９９", "010　0000　0199",
    # 줄이 바뀐 곳에서 나뉨(묶음 사이·묶음 가운데·들여쓰기)
    "010-0000-\n0199", "010-\n0000-0199", "010-0000-\r\n    0199", "010 0000\n0199", "010-00\n00-0199",
    "0100000\n0199", "010-0000-01\n99",
    # 한 자씩 띄움
    "0 1 0 0 0 0 0 0 1 9 9",
    # 나라 밖 번호(+ 가 붙은 꼴)
    "+1 212 000 0199", "+84 90 000 0199",
    # 한글로 읽은 숫자
    "공일공 공공공공 공일구구", "공일공-공공공공-공일구구", "공일공공공공공공일구구", "영일영 공공공공 공일구구",
    "공일공, 공공공공, 공일구구", "공 일 공 공 공 공 공 공 일 구 구", "공이 공공공 공일구구", "공일공\n공공공공 공일구구",
    "공일공 0000 0199", "010 공공공공 0199",
    # 소리 내어 읽을 때 줄표 자리의 「에」(받아쓰기 꼴)
    "공일공에 공공공공에 공일구구", "공일공에공공공공에공일구구", "영일영에 공공공공에 공일구구", "010에 0000에 0199",
    "공이에 공공공에 공일구구",
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
    ("to=%2B821000000199", "to=%2B[번호]"),
    ("A1210-010-0000-0199", "A1210-[번호]"),
    ("3,010-0000-0199", "3,[번호]"),  # CSV 한 줄(순번,번호)
    ("(010-0000-0199)", "([번호])"),
    ("010-0000-0199, 02-000-0198", "[번호], [번호]"),
    ("010-0000-0199 010-0000-0198", "[번호] [번호]"),
    ("2026-11-24 010-0000-0199", "2026-11-24 [번호]"),
    ("010-0000-0199 2026-11-24 09:00", "[번호] 2026-11-24 09:00"),
    ("2026.11.24. 010-0000-0199", "2026.11.24. [번호]"),
    ("11월 24일 오전 9시 010-0000-0199 박현장", "11월 24일 오전 9시 [번호] 박현장"),
    ("A1210 철근 6명, 문의 070-0000-0199.", "A1210 철근 6명, 문의 [번호]."),
])
def test_hide_phones_inside_sentences(text, expected):
    assert hide_phones(text) == expected


@pytest.mark.parametrize("text", [
    "11월 24일 A1210 6명",
    # 날짜
    "2026-11-24", "2026.11.24", "2026. 11. 24.", "20261124", "2026/11/24", "2026-11-24 09:00~18:00",
    "2026-02-01, 2026-02-02", "2026-02-01\n2026-02-02", "2026-03-12, 2026-03-13", "02-01 ~ 02-12",
    "2026년 11월 24일 오전 9시", "26.02.01 ~ 26.03.31",
    # 시각
    "09:00-18:00", "0800-1700", "야간 1800-2000 작업", "1500~1800",
    # 금액·수량
    "1,500,000원", "1,020,000,000원", "15,000,000원", "150000000원", "₩12,345,678", "3,010,000원", "1.020.000원",
    "합계 31,000,000원(부가세 3,100,000원)", "철근 0.5t, 12개, 300m",
    # 그 밖의 숫자
    "사업자 123-45-67890", "ID 120100000001995", "A동 3층 302호 12명", "버전 1.2.3",
    # 대표번호·짧은 조각은 사람 번호가 아니다(phone.normalize 도 받지 않는다)
    "대표번호 1588-0199", "1600-0199", "뒷자리 0199", "0000-0199", "010", "010-0000",
    # 숫자처럼 읽히는 한글 낱말
    "공사 일정은 이 일 정도", "공사 일이 삼일 이상 걸립니다", "일일 공사 일지", "시공사 오일 사이", "이삼일 공사",
    "구일 오후 이사", "공사 공정 일일 점검 사일 오일", "현장에 이사 오일", "3일에 2명", "공사 일이 삼일에 이사",
    "2026년 2월 1일에 02 회의",
    # 이미 가린 꼴
    "010-****-0199", "[번호]",
])
def test_hide_phones_keeps_dates_amounts_and_words(text):
    assert hide_phones(text) == text


def test_hide_phones_keeps_dates_and_ids():
    assert hide_phones("11월 24일 A1210 6명") == "11월 24일 A1210 6명"


def test_hide_phones_long_text_is_linear():
    text = ("1 " * 20000) + "010-0000-0199"
    assert hide_phones(text).endswith(PHONE_MASK)


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


def test_scrub_key_that_contains_digits_of_a_number():
    secret = "01000000199-secret"
    out = scrub(f"key={secret} to={SENTINEL_PHONE}", [secret])
    assert "0199" not in out and "secret" not in out


@pytest.fixture
def keys(monkeypatch):
    """로그 거르개가 지울 비밀 목록(시험이 끝나면 원래 거르개로 돌아간다)."""
    monkeypatch.setattr(redact, "_FILTER", redact._FILTER)
    install(lambda: [SENTINEL_KEY, ACCOUNT])


def test_log_filter(caplog, keys):
    logging.getLogger("app.outreach").warning("to %s", SENTINEL_PHONE)
    assert caplog.records and "0199" not in caplog.text
    assert_clean(caplog, ACCOUNT)


def test_log_filter_covers_child_loggers_made_later(caplog, keys):
    """거르개는 app.outreach 아래 모든 로거에 걸린다(로거 거르개는 자식에게 물려지지 않는다)."""
    logging.getLogger("app.outreach.harness.gate.t62_new_child").warning("to %s key=%s", SENTINEL_PHONE, SENTINEL_KEY)
    assert_clean(caplog)


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
        raise ValueError(f"provider said {SENTINEL_PHONE} for {SENTINEL_KEY} at {ACCOUNT}")
    except ValueError:
        logging.getLogger("app.outreach.t62").exception("보내기 실패")
    assert "ValueError" in caplog.text and "보내기 실패" in caplog.text
    assert_clean(caplog, ACCOUNT)


def test_log_filter_hides_line_when_secrets_cannot_be_read(caplog, monkeypatch):
    monkeypatch.setattr(redact, "_FILTER", redact._FILTER)

    def broken() -> list[str]:
        raise RuntimeError("db down")

    install(broken)
    logging.getLogger("app.outreach.t62").warning("key=%s to=%s", SENTINEL_KEY, SENTINEL_PHONE)
    assert caplog.records[-1].getMessage() == redact.HIDDEN_LINE
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
    assert_clean(caplog)


def test_hide_secrets_as_plain_filter():
    record = logging.LogRecord("x", logging.WARNING, __file__, 1, "to %s key %s", (SENTINEL_PHONE, SENTINEL_KEY), None)
    assert HideSecrets(lambda: [SENTINEL_KEY]).filter(record)
    assert record.getMessage() == f"to {PHONE_MASK} key [키지움]"


def test_phone_filter_is_on_without_install(caplog):
    """app.outreach 를 불러오기만 해도 번호 지우기는 켜져 있다(키 목록은 install 이 준다)."""
    logging.getLogger("app.outreach.t62").warning("to %s", SENTINEL_PHONE)
    assert "0199" not in caplog.text
