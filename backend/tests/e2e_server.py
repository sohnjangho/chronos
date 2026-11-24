"""화면 끝에서 끝까지(scripts/e2e-local.sh)가 띄우는 시험 전용 서버 — 앱을 그대로 띄우되 내 컴퓨터 밖으로는 나가지 못한다.

`python -m tests.e2e_server --host 127.0.0.1 --port 8310` (cwd = backend). 제품 코드는 바꾸지 않는다.

- 소켓 막이: tests/provider_doubles.py 와 같은 규칙 — `socket.socket.connect`·`connect_ex`·`socket.getaddrinfo` 가 내 컴퓨터
  (127.0.0.0/8 · ::1 · localhost) 밖을 향하면 `ConnectionRefusedError` 로 막는다. httpx·aiohttp(음성 SDK)·websockets·google
  genai 어느 것으로 나가든 같다. 푸는 표시는 없다.
- 막은 것은 숨기지 않는다: 막을 때마다 한 줄(무엇을 · 호스트)을 환경 변수 CHRONOS_E2E_REFUSED_LOG 의 파일에 붙인다. 화면 시험은
  끝에 그 파일을 읽고, 줄이 하나라도 있으면 실패한다. 경로·본문·키는 적지 않는다(호스트만).
- 그 변수가 없으면 뜨지 않는다(막은 것을 알릴 곳이 없으면 시험 서버가 아니다).
- **이벤트 루프는 asyncio**(`loop="asyncio"`, `http="h11"`): uvicorn 의 기본(auto)은 깔린 uvloop 를 고르는데, uvloop 는 이름 풀이·연결을
  libuv(C)로 해서 위의 파이썬 막이를 지나가지 않는다. asyncio 루프는 `socket.getaddrinfo`·`socket.connect` 를 부르므로 막힌다.
- 막이 확인용 길(시험 전용): CHRONOS_E2E_GUARD_PROBE=1 일 때만 `GET /__e2e/guard-probe` 를 더한다 — 서버 루프 위에서
  `asyncio.open_connection("example.invalid", 443)` 과 비동기 httpx GET 을 해 보고 각각 어떻게 끝났는지와 루프 종류를 준다
  (tests/e2e/test_e2e_server_guard.py 가 쓴다).
"""

import argparse
import asyncio
import ipaddress
import os
import socket
import sys
import threading
from datetime import UTC, datetime

LOG_ENV = "CHRONOS_E2E_REFUSED_LOG"
PROBE_ENV = "CHRONOS_E2E_GUARD_PROBE"
PROBE_PATH = "/__e2e/guard-probe"
PROBE_HOST = "example.invalid"
_REAL = {"connect": socket.socket.connect, "connect_ex": socket.socket.connect_ex, "getaddrinfo": socket.getaddrinfo}
_lock = threading.Lock()


def is_loopback(host: object) -> bool:
    """내 컴퓨터 안을 가리키는가(127.0.0.0/8 · ::1 · localhost)."""
    text = host.decode(errors="replace") if isinstance(host, bytes) else str(host)
    try:
        return ipaddress.ip_address(text.split("%")[0]).is_loopback
    except ValueError:
        return text.lower() == "localhost"


def _refuse(what: str, host: object) -> None:
    host = host.decode(errors="replace") if isinstance(host, bytes) else host  # httpcore 는 이름을 bytes 로 넘긴다
    line = f"{datetime.now(UTC).isoformat(timespec='seconds')} {what} {host}\n"
    with _lock, open(os.environ[LOG_ENV], "a", encoding="utf-8") as log:
        log.write(line)
    raise ConnectionRefusedError(f"e2e 시험 서버: 내 컴퓨터 밖({host})으로는 나갈 수 없습니다")


def _check(sock: socket.socket, address: object) -> None:
    if sock.family not in (socket.AF_INET, socket.AF_INET6):
        return
    host = address[0] if isinstance(address, tuple) and address else address
    if not is_loopback(host):
        _refuse("connect", host)


def _connect(self: socket.socket, address: object) -> None:
    _check(self, address)
    return _REAL["connect"](self, address)


def _connect_ex(self: socket.socket, address: object) -> int:
    _check(self, address)
    return _REAL["connect_ex"](self, address)


def _getaddrinfo(host: object, *args: object, **kwargs: object) -> list:
    if host is not None and not is_loopback(host):
        _refuse("getaddrinfo", host)
    return _REAL["getaddrinfo"](host, *args, **kwargs)


def install() -> None:
    socket.socket.connect = _connect
    socket.socket.connect_ex = _connect_ex
    socket.getaddrinfo = _getaddrinfo


async def _attempt(work) -> str:
    """바깥 연결 한 번 — 끝난 꼴을 글로(성공이면 "connected")."""
    try:
        await asyncio.wait_for(work(), timeout=5)
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 그 종류를 돌려준다
        return type(exc).__name__
    return "connected"


async def _guard_probe() -> dict:
    import httpx

    async def raw() -> None:
        _reader, writer = await asyncio.open_connection(PROBE_HOST, 443)
        writer.close()

    async def http() -> None:
        async with httpx.AsyncClient() as client:
            await client.get(f"https://{PROBE_HOST}/")

    loop = asyncio.get_running_loop()
    return {"loop": f"{type(loop).__module__}.{type(loop).__name__}", "open_connection": await _attempt(raw),
            "httpx": await _attempt(http)}


def _app():
    from app.main import app

    if os.environ.get(PROBE_ENV) == "1":
        app.add_api_route(PROBE_PATH, _guard_probe, methods=["GET"], include_in_schema=False)
    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if not os.environ.get(LOG_ENV):
        sys.exit(f"{LOG_ENV} 가 없습니다 — 막은 연결을 적을 파일이 있어야 뜹니다")
    if not is_loopback(args.host):
        sys.exit("시험 서버는 내 컴퓨터 안(127.0.0.1)에서만 뜹니다")
    install()  # 앱을 불러오기 전에(앱이 불러오는 라이브러리가 뜨면서 나가도 막히게)
    import uvicorn

    uvicorn.run(_app(), host=args.host, port=args.port, loop="asyncio", http="h11")


if __name__ == "__main__":
    main()
