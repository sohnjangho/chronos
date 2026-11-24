"""내 사진 배경(PUT·GET·DELETE /api/me/wallpaper) — 한 사람에 한 장, 본인만 읽는다.

형식은 파일 앞 바이트(매직 바이트)로 본다(JPG·PNG·WebP). 10MB 까지, 가로·세로 8000 까지. 응답에 파일 이름·경로·EXIF 를 싣지 않는다.
"""

import struct
import zlib
from datetime import timedelta

from app.programs.wallpaper import image
from app.store.tables import User
from app.store.wallpapers import UserWallpaper
from tests.helpers import auth


def png(w: int = 4, h: int = 3) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\x00" + b"\x80\x80\x80" * w for _ in range(h))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def jpeg(w: int = 640, h: int = 480, exif: bytes = b"") -> bytes:
    app1 = b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif if exif else b""
    sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, h, w, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app1 + sof0 + b"\xff\xda\x00\x02" + b"\x00" * 16 + b"\xff\xd9"


def webp(w: int = 300, h: int = 200) -> bytes:
    # VP8X: 깃발 4바이트 + (가로-1)·(세로-1) 3바이트씩
    vp8x = b"\x00\x00\x00\x00" + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little")
    body = b"WEBP" + b"VP8X" + struct.pack("<I", len(vp8x)) + vp8x
    return b"RIFF" + struct.pack("<I", len(body)) + body


def put(client, headers, data: bytes, content_type: str = "image/png"):
    return client.put("/api/me/wallpaper", content=data, headers={**headers, "Content-Type": content_type})


def test_requires_login(client):
    assert client.get("/api/me/wallpaper").status_code == 401
    assert client.put("/api/me/wallpaper", content=png()).status_code == 401
    assert client.delete("/api/me/wallpaper").status_code == 401


def test_none_yet_is_404(client, user):
    assert client.get("/api/me/wallpaper", headers=user).status_code == 404


def test_put_png_then_get_bytes(client, user):
    data = png(4, 3)
    r = put(client, user, data)
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "image/png" and body["width"] == 4 and body["height"] == 3 and body["bytes"] == len(data)
    assert set(body) == {"type", "width", "height", "bytes", "updated_at"}
    got = client.get("/api/me/wallpaper", headers=user)
    assert got.status_code == 200
    assert got.content == data
    assert got.headers["content-type"] == "image/png"
    assert "private" in got.headers["cache-control"]
    assert got.headers["x-content-type-options"] == "nosniff"


def test_type_comes_from_magic_bytes_not_header(client, user):
    # 머리글이 png 라고 해도 내용이 JPEG 이면 JPEG 로, 반대로 이름·머리글이 그림이어도 내용이 아니면 415.
    r = put(client, user, jpeg(), content_type="image/png")
    assert r.status_code == 200 and r.json()["type"] == "image/jpeg"
    assert (r.json()["width"], r.json()["height"]) == (640, 480)
    assert client.get("/api/me/wallpaper", headers=user).headers["content-type"] == "image/jpeg"
    for bad in (b"GIF89a" + b"\x00" * 20, b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"%PDF-1.7", b"", b"\x89PNG\r\n"):
        r = put(client, user, bad)
        assert r.status_code == 415 and r.json()["code"] == "wallpaper_bad_type", bad[:8]
        assert "JPG" in r.json()["message"]


def test_webp_is_accepted(client, user):
    r = put(client, user, webp(300, 200), content_type="application/octet-stream")
    assert r.status_code == 200
    assert (r.json()["type"], r.json()["width"], r.json()["height"]) == ("image/webp", 300, 200)


def test_too_big_is_413(client, user):
    big = png() + b"\x00" * (10 * 1024 * 1024)
    r = put(client, user, big)
    assert r.status_code == 413 and r.json()["code"] == "wallpaper_too_large"
    assert "10MB" in r.json()["message"]
    assert client.get("/api/me/wallpaper", headers=user).status_code == 404


def test_declared_length_over_limit_is_refused_before_reading(client, user, monkeypatch):
    # Content-Length 가 넘으면 본문을 읽지 않고 막는다.
    from starlette.requests import Request

    async def boom(self):
        raise AssertionError("본문을 읽었다")

    monkeypatch.setattr(Request, "stream", boom)
    r = client.put(
        "/api/me/wallpaper",
        content=b"x",
        headers={**user, "Content-Type": "image/png", "Content-Length": str(10 * 1024 * 1024 + 1)},
    )
    assert r.status_code == 413


def test_too_many_pixels_is_422(client, user):
    r = put(client, user, jpeg(8001, 100), content_type="image/jpeg")
    assert r.status_code == 422 and r.json()["code"] == "wallpaper_too_wide"
    assert put(client, user, jpeg(8000, 8000), content_type="image/jpeg").status_code == 200


def test_new_upload_overwrites(client, user):
    put(client, user, png(4, 3))
    second = jpeg(10, 20)
    put(client, user, second, content_type="image/jpeg")
    got = client.get("/api/me/wallpaper", headers=user)
    assert got.content == second and got.headers["content-type"] == "image/jpeg"


def test_other_user_cannot_see_or_delete_mine(client, user, admin):
    put(client, user, png())
    assert client.get("/api/me/wallpaper", headers=admin).status_code == 404
    assert client.delete("/api/me/wallpaper", headers=admin).status_code == 204
    assert client.get("/api/me/wallpaper", headers=user).status_code == 200
    # 경로에 남의 id 를 넣을 길이 없다
    assert client.get("/api/me/wallpaper/1", headers=admin).status_code in (404, 405)


def test_delete_removes(client, user):
    put(client, user, png())
    assert client.delete("/api/me/wallpaper", headers=user).status_code == 204
    assert client.get("/api/me/wallpaper", headers=user).status_code == 404
    assert client.delete("/api/me/wallpaper", headers=user).status_code == 204  # 없어도 조용히


def test_no_names_or_exif_echoed(client, user):
    exif = b"Exif\x00\x00secret-camera-serial /Users/someone/IMG_0001.jpg"
    r = client.put(
        "/api/me/wallpaper",
        content=jpeg(exif=exif),
        headers={**user, "Content-Type": "image/jpeg", "Content-Disposition": 'attachment; filename="IMG_0001.jpg"'},
    )
    assert r.status_code == 200
    assert "IMG_0001" not in r.text and "secret" not in r.text and "/Users" not in r.text
    got = client.get("/api/me/wallpaper", headers=user)
    assert "content-disposition" not in got.headers


def test_rows_older_than_the_account_are_not_served(client, session, user_token):
    user = session.get(User, 2)
    session.add(
        UserWallpaper(
            user_id=user.id, mime="image/png", width=1, height=1, data=png(1, 1),
            updated_at=user.created_at - timedelta(days=1),
        )
    )
    session.commit()
    assert client.get("/api/me/wallpaper", headers=auth(user_token)).status_code == 404


def test_sniff_dimensions_unit():
    assert image.sniff(png(7, 9)) == ("image/png", 7, 9)
    assert image.sniff(jpeg(123, 45)) == ("image/jpeg", 123, 45)
    assert image.sniff(webp(16, 9)) == ("image/webp", 16, 9)
    # VP8L(무손실) 머리: 서명 0x2f 뒤 14비트씩 (가로-1)·(세로-1)
    bits = (50 - 1) | ((40 - 1) << 14)
    vp8l = b"\x2f" + bits.to_bytes(4, "little")
    body = b"WEBP" + b"VP8L" + struct.pack("<I", len(vp8l)) + vp8l
    assert image.sniff(b"RIFF" + struct.pack("<I", len(body)) + body) == ("image/webp", 50, 40)
    assert image.sniff(b"not an image") is None
