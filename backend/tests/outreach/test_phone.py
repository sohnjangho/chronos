"""전화번호 정리·종류·가능 채널·가리기·묶음 손잡이(Task 62). 휴대전화는 가상(가운데 0000), 지역 번호는 국번 2~9 가 있어야
번호라서 2000 꼴을 쓴다(아무 데도 걸지 않는다)."""

import pytest

from app.outreach.phone import (
    NO_NUMBER,
    can_call,
    can_sms,
    is_mobile,
    kind,
    mask,
    mask_bad,
    normalize,
    peer_key,
    storable,
)

WIDE_MOBILE = "".join(chr(0xFF10 + int(c)) for c in "01000000199")


@pytest.mark.parametrize("raw", [
    "010-0000-0199", "010 0000 0199", "010.0000.0199", "01000000199", " 010-0000-0199\n",
    "010 - 0000 - 0199", "(010) 0000-0199", "010–0000–0199", "010—0000—0199",  # 줄표 여러 꼴
    "+82 10-0000-0199", "+82-10-0000-0199", "+821000000199", "+82 (0)10-0000-0199", "+82 010-0000-0199",
    "82-10-0000-0199", "821000000199", "0082-10-0000-0199", "(+82) 10-0000-0199",
    "０１０－００００－０１９９", WIDE_MOBILE, "＋８２　１０　００００　０１９９",  # 전각 숫자·기호·빈칸
    "010-0000-\n0199",  # 줄이 바뀐 곳에서 나뉨
    "010\u200b0000\u200b0199", "\ufeff010-0000-0199", "010\u00ad0000\u00ad0199", "0\u200d10-0000-0199",  # 폭 없는 글자
])
def test_normalize_variants(raw):
    assert normalize(raw) == "01000000199"


@pytest.mark.parametrize(("raw", "expected"), [
    ("02-200-0199", "022000199"),  # 서울 9자리
    ("02-2000-0199", "0220000199"),
    ("+82 2-2000-0199", "0220000199"),
    ("(02) 200-0199", "022000199"),
    ("031-200-0199", "0312000199"),
    ("064-2000-0199", "06420000199"),
    ("051.900.0199", "0519000199"),
    ("070-0000-0199", "07000000199"),  # 인터넷 전화
    ("+82 70 0000 0199", "07000000199"),
    ("011-000-0199", "0110000199"),  # 옛 휴대전화 10자리
    ("019-0000-0199", "01900000199"),
    ("1588-0199", "15880199"),  # 대표번호 8자리
    ("15880199", "15880199"),
    (" 1644 0199", "16440199"),
    ("1800-0199", "18000199"),
    ("0507-1234-0199", "050712340199"),  # 안심번호 12자리
    ("0505-000-0199", "05050000199"),
    ("080-000-0199", "0800000199"),  # 수신자 부담
    ("060-000-0199", "0600000199"),  # 정보 이용(저장은 storable 이 막는다)
    ("+82 1588 0199", "15880199"),  # 대표번호의 다른 꼴: +82 뒤·지역 번호 뒤
    ("+8215880199", "15880199"),
    ("0082-1644-0199", "16440199"),
    ("02-1588-0000", "15880000"),
    ("031-1588-0000", "15880000"),
    ("(02) 1800-0199", "18000199"),
])
def test_normalize_every_domestic_kind(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize("raw", [
    None, "", "   ", "010-12-34",
    "010-0000-019", "010-0000-01990", "0100000019",  # 자리 수가 맞지 않음
    "010-000-0199", "070-000-0199",  # 010·070 은 가운데 4자리
    "012-0000-0199", "039-200-0199", "00-0000-0199", "050-0000-0199", "1300-0199", "1588-019",  # 없는 앞자리·자리 수
    "02-000-0199", "02-1200-0199", "031-0900-1800",  # 지역 번호의 국번은 2~9 로 시작한다
    "10-0000-0199",  # 앞 0 이 빠짐
    "+1 212 000 0199", "+84 90 000 0199",  # 나라 밖 번호
    "010-0000-0199 (휴대폰)", "tel:010-0000-0199", "010/0000/0199", "010-0000-0199, 010-0000-0198",
    "공일공 공공공공 공일구구", "2026-11-24", "20261124", "1,500,000",
    "+82+10-0000-0199", "010-0000-0199+", "++82 10 0000 0199",
    "+82 1300 0199", "02-1300-0000",  # 15·16·18 밖의 대표번호 꼴
])
def test_normalize_rejects(raw):
    assert normalize(raw) is None


@pytest.mark.parametrize(("number", "expected"), [
    ("01000000199", "mobile"), ("+82 10-0000-0199", "mobile"), ("0110000199", "mobile"),
    ("0220000199", "landline"), ("0312000199", "landline"),
    ("07000000199", "internet"),
    ("15880199", "rep"), ("1800-0199", "rep"),
    ("050712340199", "safe"),
    ("0800000199", "tollfree"),
    ("0600000199", "premium"),
    ("010-12-34", None), (None, None),
])
def test_kind(number, expected):
    assert kind(number) == expected


@pytest.mark.parametrize(("number", "store", "sms", "call"), [
    ("010-0000-0199", True, True, True),
    ("02-2000-0199", True, False, True),
    ("070-0000-0199", True, False, True),
    ("1588-0199", True, False, True),
    ("0507-1234-0199", True, False, True),
    ("080-000-0199", True, False, True),
    ("060-000-0199", False, False, False),
    ("010-12-34", False, False, False),
    (None, False, False, False),
])
def test_storable_can_sms_can_call(number, store, sms, call):
    assert (storable(number), can_sms(number), can_call(number)) == (store, sms, call)


def test_is_mobile():
    assert is_mobile("01000000199") and is_mobile("010-0000-0199") and is_mobile("0110000199")
    assert not is_mobile("0220000199") and not is_mobile("07000000199") and not is_mobile("15880199")
    assert not is_mobile(None) and not is_mobile("")


@pytest.mark.parametrize(("number", "expected"), [
    ("01000000199", "010-****-0199"),
    ("0110000199", "011-****-0199"),
    ("022000199", "02-****-0199"),
    ("0220000199", "02-****-0199"),
    ("0312000199", "031-****-0199"),
    ("07000000199", "070-****-0199"),
    ("050712340199", "0507-****-0199"),
    ("0800000199", "080-****-0199"),
    ("15880199", "1588-****"),  # 대표번호는 가운데가 없다 — 끝 4자리를 가린다
    ("+82 10-0000-0199", "010-****-0199"),  # 정리 전 꼴이 와도 가린다
    (None, NO_NUMBER),
])
def test_mask(number, expected):
    assert mask(number) == expected


def test_mask_never_echoes_a_bad_number():
    assert mask("010-12-345") == mask_bad("010-12-345")
    assert "12-345" not in mask("010-12-345")


@pytest.mark.parametrize(("raw", "shown"), [
    ("010-12-345", "01…"),
    ("０１０-１２-３４５", "01…"),
    ("  0100000019999  ", "01…"),
    ("전화 010-0000-0199 아님", "전화…"),
    ("0101", "01…"),  # 짧으면 반까지만
    ("010", "0…"),
    ("7", "…"),
])
def test_mask_bad_shows_at_most_two_and_never_most_of_it(raw, shown):
    assert mask_bad(raw) == shown


def test_mask_bad_empty():
    assert mask_bad("") == NO_NUMBER and mask_bad("   ") == NO_NUMBER


def test_peer_key_is_stable_and_not_reversible():
    key = peer_key("01000000199")
    assert key == peer_key("01000000199") and "0199" not in key
    assert len(key) == 12 and all(c in "0123456789abcdef" for c in key)


@pytest.mark.parametrize("forms", [
    ["010-0000-0199", "+82 10-0000-0199", "(+82) 10-0000-0199", "01000000199", "010\u200b0000\u200b0199"],
    ["02-2000-0199", "+82 2 2000 0199", "0220000199"],
    ["1588-0199", "15880199", " 1588 0199", "+82 1588 0199", "02-1588-0199"],
    ["0507-1234-0199", "050712340199"],
    ["080-000-0199", "+82 80 000 0199"],
])
def test_peer_key_is_one_per_number_for_every_kind(forms):
    assert len({peer_key(f) for f in forms}) == 1


def test_peer_key_differs_between_numbers():
    assert peer_key("01000000198") != peer_key("01000000199")


def test_peer_key_depends_on_secret_key(monkeypatch):
    before = peer_key("01000000199")
    monkeypatch.setenv("CHRONOS_SECRET_KEY", "another-secret-key-0123456789abcdef")
    assert peer_key("01000000199") != before
