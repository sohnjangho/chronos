import pytest

from app.security.crypto import SecretUnreadable, decrypt, encrypt


def test_round_trip_and_not_plain():
    token = encrypt("abcd1234efgh5678")
    assert "abcd1234" not in token and decrypt(token) == "abcd1234efgh5678"


def test_same_key_reads_across_calls():
    assert decrypt(encrypt("x")) == "x"


def test_changed_secret_key_raises(monkeypatch):
    token = encrypt("abcd1234efgh5678")
    monkeypatch.setenv("CHRONOS_SECRET_KEY", "another-secret-key-0123456789abcdef")
    with pytest.raises(SecretUnreadable) as info:
        decrypt(token)
    assert "abcd1234" not in str(info.value) and info.value.__cause__ is None
