"""통화 첫마디(Task 87): 코드가 고정 틀로 짓는 문장 — AI 임과 기록됨을 늘 밝히고, 번호와 모델 글이 들어갈 자리가 없다.
언어 표에 든 언어마다 같은 검사를 돈다(Task 100 이 언어를 더하면 그대로 따라 돈다)."""

import inspect
import re
import string

import pytest

from app.outreach import redact
from app.outreach.voice import greeting
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_PHONE

SITE, NAME = "가상 물류센터", "박현장"
LANGUAGES = sorted(greeting.FIRST_LINES)
# 같은 번호의 여러 꼴(줄표·빈칸·점·붙임·+82·한글로 읽음)
NUMBER_FORMS = (SENTINEL_PHONE, "010 0000 0199", "010.0000.0199", "01000000199", "+82 10-0000-0199",
                "공일공 공공공공 공일구구")


def _digits(text: str) -> str:
    return re.sub(r"[^0-9]", "", text)


def _fields(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name is not None}


def test_first_line_is_exact_korean_sentence():
    assert greeting.first_line("ko", "가상 물류센터", "박현장") == (
        "안녕하세요, 가상 물류센터 일정 담당 ChronOS AI 비서입니다. 이 통화는 기록됩니다. 박현장님 맞으신가요?"
    )


def test_inbound_line_names_the_site_only_when_it_is_known():
    assert greeting.inbound_line("ko", "가상 물류센터") == (
        "안녕하세요, 가상 물류센터 일정 담당 ChronOS AI 비서입니다. 이 통화는 기록됩니다. 무엇을 도와드릴까요?"
    )
    no_site = "안녕하세요, 일정 담당 ChronOS AI 비서입니다. 이 통화는 기록됩니다. 무엇을 도와드릴까요?"
    assert greeting.inbound_line("ko", None) == no_site
    assert greeting.inbound_line("ko", "") == greeting.inbound_line("ko", "   ") == no_site


@pytest.mark.parametrize("language", ["xx", "", "ja", "한국어", "ko-KR", "KO", " ko ", "ko_KR"])
def test_unknown_language_falls_back_to_korean(language):
    assert greeting.first_line(language, SITE, NAME) == greeting.first_line("ko", SITE, NAME)
    assert greeting.inbound_line(language, SITE) == greeting.inbound_line("ko", SITE)
    assert greeting.inbound_line(language, None) == greeting.inbound_line("ko", None)


def test_korean_is_always_in_the_tables():
    assert "ko" in LANGUAGES and greeting.DEFAULT_LANGUAGE == "ko"


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_language_has_all_three_lines_and_states_ai_and_recording(language):
    """언어를 더하는 작업은 세 표와 「꼭 하는 말」 표를 함께 채워야 한다 — 하나라도 빠지면 여기서 걸린다."""
    assert set(greeting.FIRST_LINES) == set(greeting.INBOUND_LINES) == set(greeting.INBOUND_LINES_NO_SITE)
    assert set(greeting.MUST_SAY) == set(greeting.FIRST_LINES)
    assert _fields(greeting.FIRST_LINES[language]) == {"site", "name"}
    assert _fields(greeting.INBOUND_LINES[language]) == {"site"}
    assert _fields(greeting.INBOUND_LINES_NO_SITE[language]) == set()
    lines = (greeting.first_line(language, SITE, NAME), greeting.inbound_line(language, SITE),
             greeting.inbound_line(language, None))
    for line in lines:
        assert "ChronOS" in line
        assert greeting.discloses(language, line), line  # AI 임 · 기록됨
        assert not _digits(line)  # 틀에는 숫자가 없다
    assert SITE in lines[0] and NAME in lines[0] and SITE in lines[1] and SITE not in lines[2]


@pytest.mark.parametrize("language", LANGUAGES)
def test_templates_hold_no_digits_and_no_other_fields(language):
    for table in (greeting.FIRST_LINES, greeting.INBOUND_LINES, greeting.INBOUND_LINES_NO_SITE):
        assert not _digits(table[language])
        assert _fields(table[language]) <= {"site", "name"}


def test_lines_are_built_from_site_and_name_only():
    """모델이 쓴 글이 들어올 인자가 없다 — 언어·현장 이름·사람 이름뿐."""
    assert list(inspect.signature(greeting.first_line).parameters) == ["language", "site", "name"]
    assert list(inspect.signature(greeting.inbound_line).parameters) == ["language", "site"]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("number", NUMBER_FORMS)
def test_a_number_typed_into_a_name_never_reaches_the_line(language, number):
    """주소록 이름·현장 이름 칸에 번호를 적어 두어도 첫마디에는 나가지 않는다(번호만 빠지고 이름은 남는다)."""
    out_line = greeting.first_line(language, f"{SITE} {number}", f"{NAME} {number}")
    in_line = greeting.inbound_line(language, f"{SITE}({number})")
    for line in (out_line, in_line):
        assert SENTINEL_DIGITS not in _digits(line) and SENTINEL_DIGITS[1:] not in _digits(line)
        assert redact.hide_phones(line) == line
        assert redact.PHONE_MASK not in line and "()" not in line
        assert SITE in line
    assert NAME in out_line
    assert out_line == greeting.first_line(language, SITE, NAME)
    assert in_line == greeting.inbound_line(language, SITE)  # 번호를 쌌던 빈 괄호도 남지 않는다


@pytest.mark.parametrize("hidden", [
    "01\u200b0-0000-0199",  # 폭 없는 글자가 묶음 가운데
    "010\u200b0000\u200b0199",
    "010\x000000\x000199",  # 제어 글자로 쪼갬
    "01\x000-0000-0199",
    "010\u202e0000\u202e0199",  # 글 방향 바꾸기 글자
    "010\n0000\n0199",
    "010-0000\x00-0199",
])
def test_a_number_split_by_invisible_or_control_characters_never_reaches_the_line(hidden):
    line = greeting.first_line("ko", f"{SITE} {hidden}", f"{NAME} {hidden}")
    assert line == greeting.first_line("ko", SITE, NAME)
    assert greeting.inbound_line("ko", hidden) == greeting.inbound_line("ko", None)


def test_name_that_is_only_a_number_is_refused_without_echoing_it():
    for site, name in ((SITE, SENTINEL_PHONE), (SENTINEL_PHONE, NAME), (SITE, ""), ("", NAME), (SITE, " \n\t ")):
        with pytest.raises(ValueError) as caught:
            greeting.first_line("ko", site, name)
        assert SENTINEL_DIGITS not in _digits(str(caught.value))
    # 받는 통화는 현장 이름이 번호뿐이면 현장 이름 없는 문장으로 받는다(받지 못하는 것보다 낫다)
    assert greeting.inbound_line("ko", SENTINEL_PHONE) == greeting.inbound_line("ko", None)


def test_line_breaks_and_control_characters_in_names_become_spaces():
    line = greeting.first_line("ko", "가상\n물류센터\t\u200b", "박\r\n현장\x00\u202e")
    assert line == greeting.first_line("ko", "가상 물류센터", "박 현장")
    assert not re.search(r"[\x00-\x1f\u200b\u202e]", line)


def test_braces_in_a_name_are_plain_text():
    line = greeting.first_line("ko", "{name} 현장", "{site}")
    assert line == "안녕하세요, {name} 현장 일정 담당 ChronOS AI 비서입니다. 이 통화는 기록됩니다. {site}님 맞으신가요?"


def test_ordinary_digits_in_a_site_name_are_kept():
    line = greeting.first_line("ko", "가상 2차 물류센터 A동 1203호", NAME)
    assert "가상 2차 물류센터 A동 1203호" in line


@pytest.mark.parametrize("spoken,expected", [
    ("안녕하세요, 가상 물류센터 일정 담당 ChronOS AI 비서입니다. 이 통화는 기록됩니다. 박현장님 맞으신가요?", True),
    ("안녕하세요 가상 물류센터 일정 담당 크로노스 에이아이 비서입니다 이 통화는 녹음됩니다", True),
    ("안녕하세요. 인공지능 비서입니다. 통화 내용은 기 록 됩니다.", True),
    ("안녕하세요, 가상 물류센터 일정 담당 ChronOS AI 비서입니다. 박현장님 맞으신가요?", False),  # 기록됨이 빠짐
    ("안녕하세요, 가상 물류센터 일정 담당 김대리입니다. 이 통화는 기록됩니다.", False),  # AI 임이 빠짐
    ("", False),
])
def test_discloses_checks_what_was_actually_spoken(spoken, expected):
    """음성 모델이 실제로 한 첫 말(받아쓰기)에 AI 임과 기록됨이 들어 있는지 — 통화 뒤 확인이 쓴다."""
    assert greeting.discloses("ko", spoken) is expected
    assert greeting.discloses("xx", spoken) is expected  # 모르는 언어는 한국어 기준
