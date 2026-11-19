"""비밀번호는 bcrypt 해시로만 저장한다."""

import bcrypt

MAX_PASSWORD_BYTES = 72  # bcrypt 가 받는 최대 길이


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    raw = password.encode()
    if len(raw) > MAX_PASSWORD_BYTES:
        return False
    return bcrypt.checkpw(raw, password_hash.encode())
