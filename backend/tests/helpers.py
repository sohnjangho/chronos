def auth(token: str) -> dict[str, str]:
    """Bearer 토큰을 요청 머리글로 바꾼다."""
    return {"Authorization": f"Bearer {token}"}
