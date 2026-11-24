"""그림 형식과 가로세로를 파일 앞 바이트로 읽는다(새 의존성 없이 머리만 본다 — 그림을 풀지 않는다)."""

import struct

_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _png(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def _jpeg(data: bytes) -> tuple[int, int] | None:
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # 채움 바이트
            i += 1
            continue
        if marker in (0x01, *range(0xD0, 0xD8)):  # 길이 없는 표지
            i += 2
            continue
        if marker in (0xD9, 0xDA):  # 끝·본문 시작 — 그 전에 크기가 없었다
            return None
        (length,) = struct.unpack(">H", data[i + 2 : i + 4])
        if marker in _SOF:
            if i + 9 > len(data):
                return None
            h, w = struct.unpack(">HH", data[i + 5 : i + 9])
            return w, h
        i += 2 + length
    return None


def _webp(data: bytes) -> tuple[int, int] | None:
    kind, body = data[12:16], data[20:]
    if kind == b"VP8X" and len(body) >= 10:
        return int.from_bytes(body[4:7], "little") + 1, int.from_bytes(body[7:10], "little") + 1
    if kind == b"VP8L" and len(body) >= 5 and body[0] == 0x2F:
        bits = int.from_bytes(body[1:5], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if kind == b"VP8 " and len(body) >= 10 and body[3:6] == b"\x9d\x01\x2a":
        w, h = struct.unpack("<HH", body[6:10])
        return w & 0x3FFF, h & 0x3FFF
    return None


def sniff(data: bytes) -> tuple[str, int, int] | None:
    """(형식, 가로, 세로). JPG·PNG·WebP 가 아니거나 머리를 못 읽으면 None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime, size = "image/png", _png(data)
    elif data.startswith(b"\xff\xd8\xff"):
        mime, size = "image/jpeg", _jpeg(data)
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        mime, size = "image/webp", _webp(data)
    else:
        return None
    if size is None or size[0] <= 0 or size[1] <= 0:
        return None
    return mime, size[0], size[1]
