"""전화번호 정리·가리기·묶음 손잡이(Task 62). 번호는 모두 가상(가운데 0000)."""

import pytest

from app.outreach.phone import NO_NUMBER, is_mobile, mask, mask_bad, normalize, peer_key


@pytest.mark.parametrize("raw", [
    "010-0000-0199", "010 0000 0199", "010.0000.0199", "01000000199", " 010-0000-0199\n",
    "010 - 0000 - 0199", "(010) 0000-0199", "010–0000–0199", "010—0000—0199",  # 줄표 여러 꼴
    "+82 10-0000-0199", "+82-10-0000-0199", "+821000000199", "+82 (0)10-0000-0199", "+82 010-0000-0199",
    "82-10-0000-0199", "821000000199", "0082-10-0000-0199",
    "０１０－００００－０１９９", "０１００００００１９９", "＋８２　１０　００００　０１９９",  # 전각 숫자·기호·빈칸
    "010-0000-\n0199",  # 줄이 바뀐 곳에서 나뉨
])
def test_normalize_variants(raw):
    assert normalize(raw) == "01000000199"


@pytest.mark.parametrize(("raw", "expected"), [
    ("02-000-0199", "020000199"),  # 서울 9자리
    ("02-0000-0199", "0200000199"),
    ("+82 2-0000-0199", "0200000199"),
    ("(02) 000-0199", "020000199"),
    ("031-000-0199", "0310000199"),
    ("064-0000-0199", "06400000199"),
    ("051.000.0199", "0510000199"),
    ("070-0000-0199", "07000000199"),  # 인터넷 전화
    ("+82 70 0000 0199", "07000000199"),
    ("011-000-0199", "0110000199"),  # 옛 휴대전화 10자리
    ("019-0000-0199", "01900000199"),
])
def test_normalize_area_and_070(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize("raw", [
    None, "", "   ", "010-12-34",
    "010-0000-019", "010-0000-01990", "0100000019",  # 자리 수가 맞지 않음
    "010-000-0199",  # 010 은 가운데 4자리
    "070-000-0199",  # 070 도 가운데 4자리
    "012-0000-0199", "039-000-0199", "00-0000-0199",  # 없는 앞자리
    "1588-0199", "15880199", "1600-0199", "1800-0199",  # 대표번호 — 사람에게 닿지 않고 문자를 받지 못한다
    "080-000-0199", "060-000-0199", "0505-000-0199",  # 수신자 부담·정보 이용·안심번호
    "10-0000-0199",  # 앞 0 이 빠짐
    "+1 212 000 0199", "+84 90 000 0199",  # 나라 밖 번호
    "010-0000-0199 (휴대폰)", "tel:010-0000-0199", "010/0000/0199", "010-0000-0199, 010-0000-0198",
    "공일공 공공공공 공일구구", "2026-11-24", "20261124", "1,500,000",
    "+82+10-0000-0199", "010-0000-0199+",
])
def test_normalize_rejects(raw):
    assert normalize(raw) is None


def test_is_mobile():
    assert is_mobile("01000000199") and is_mobile("010-0000-0199") and is_mobile("0110000199")
    assert not is_mobile("0200000199") and not is_mobile("07000000199") and not is_mobile("0310000199")
    assert not is_mobile(None) and not is_mobile("") and not is_mobile("1588-0199")


@pytest.mark.parametrize(("number", "expected"), [
    ("01000000199", "010-****-0199"),
    ("0110000199", "011-****-0199"),
    ("020000199", "02-****-0199"),
    ("0200000199", "02-****-0199"),
    ("0310000199", "031-****-0199"),
    ("07000000199", "070-****-0199"),
    ("+82 10-0000-0199", "010-****-0199"),  # 정리 전 꼴이 와도 가린다
    (None, NO_NUMBER),
])
def test_mask(number, expected):
    assert mask(number) == expected


def test_mask_never_echoes_a_bad_number():
    assert mask("010-12-345") == mask_bad("010-12-345")
    assert "12-345" not in mask("010-12-345")


@pytest.mark.parametrize(("raw", "head"), [
    ("010-12-345", "010"),
    ("０１０-１２-３４５", "010"),
    ("  0100000019999  ", "010"),
    ("전화 010-0000-0199 아님", "전화 "),
])
def test_mask_bad_keeps_first_three_only(raw, head):
    shown = mask_bad(raw)
    assert shown.startswith(head) and "0199" not in shown and "345" not in shown
    assert len(shown.replace(head, "", 1)) <= 1  # 앞 3자리와 줄임표 하나


def test_mask_bad_empty():
    assert mask_bad("") == NO_NUMBER and mask_bad("   ") == NO_NUMBER


def test_peer_key_is_stable_and_not_reversible():
    key = peer_key("01000000199")
    assert key == peer_key("01000000199") and "0199" not in key
    assert len(key) == 12 and all(c in "0123456789abcdef" for c in key)


def test_peer_key_groups_written_forms_of_one_number():
    assert peer_key("010-0000-0199") == peer_key("+82 10-0000-0199") == peer_key("01000000199")
    assert peer_key("01000000198") != peer_key("01000000199")


def test_peer_key_depends_on_secret_key(monkeypatch):
    before = peer_key("01000000199")
    monkeypatch.setenv("CHRONOS_SECRET_KEY", "another-secret-key-0123456789abcdef")
    assert peer_key("01000000199") != before
