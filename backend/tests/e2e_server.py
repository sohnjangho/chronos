"""화면 끝에서 끝까지(scripts/e2e-local.sh)가 띄우는 시험 전용 서버 — 앱을 그대로 띄우되 내 컴퓨터 밖으로는 나가지 못한다.

`python -m tests.e2e_server --host 127.0.0.1 --port 8310` (cwd = backend). 제품 코드는 바꾸지 않는다.

- 소켓 막이: tests/provider_doubles.py 와 같은 규칙 — `socket.socket.connect`·`connect_ex`·`socket.getaddrinfo` 가 내 컴퓨터
  (127.0.0.0/8 · ::1 · localhost) 밖을 향하면 `ConnectionRefusedError` 로 막는다. httpx·aiohttp(음성 SDK)·websockets·google
  genai 어느 것으로 나가든 같다. 푸는 표시는 없다.
- 막은 것은 숨기지 않는다: 막을 때마다 한 줄(무엇을 · 호스트)을 환경 변수 CHRONOS_E2E_REFUSED_LOG 의 파일에 붙인다. 화면 시험은
  끝에 그 파일을 읽고, 줄이 하나라도 있으면 실패한다. 경로·본문·키는 적지 않는다(호스트만).
- 그 변수가 없으면 뜨지 않는다(막은 것을 알릴 곳이 없으면 시험 서버가 아니다).
"""

import argparse
import ipaddress
import os
import socket
import sys
import threading
from datetime import UTC, datetime

LOG_ENV = "CHRONOS_E2E_REFUSED_LOG"
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

    uvicorn.run("app.main:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
