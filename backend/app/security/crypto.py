"""API 키 같은 비밀값을 DB에 넣기 전에 Fernet 으로 암호화한다.

키는 Settings.secret_key 에서 SHA-256 으로 유도한다. secret_key 가 바뀌면 예전 값은 풀 수 없다.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings


class SecretUnreadable(Exception):
    """저장된 암호문을 지금 키로 풀 수 없다(secret_key 가 바뀌었다)."""


def _fernet() -> Fernet:
    digest = hashlib.sha256(b"chronos-secret:" + Settings().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise SecretUnreadable("stored secret cannot be decrypted") from None
