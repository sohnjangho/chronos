"""화면 시험 서버(tests/e2e_server.py)의 바깥 연결 막이가 **서버 자기 루프 위의 비동기 길**에서도 듣는지 — 실제로 띄워 본다.

감싸개를 빈 포트에 띄우고(임시 data · 일꾼 끔 · CHRONOS_E2E_GUARD_PROBE=1), 시험 전용 길이 서버 루프에서
`asyncio.open_connection("example.invalid", 443)` 과 비동기 httpx GET 을 해 본다. 둘 다 막혀(연결 없음) 막은 호스트 기록에 남아야
하고, 루프는 uvloop 가 아니라 asyncio 여야 한다(uvloop 는 libuv 로 이름을 풀고 연결해 파이썬 막이를 지나간다). 이 시험 프로세스는
내 컴퓨터 안(127.0.0.1)으로만 묻는다.
"""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from tests.provider_doubles import time_limit

BACKEND = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_server_loop_outbound_attempts_are_refused_and_recorded(tmp_path):
    port, log = _free_port(), tmp_path / "refused-hosts.log"
    log.write_text("", encoding="utf-8")
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path), "LANG": "C.UTF-8",
           "CHRONOS_DATA_DIR": str(tmp_path / "data"), "CHRONOS_SECRET_KEY": "e2e-guard-0123456789abcdef0123456789abcdef",
           "CHRONOS_ADMIN_ID": "admin", "CHRONOS_ADMIN_PASSWORD": "guard-pass", "CHRONOS_QDRANT_URL": "",
           "CHRONOS_OUTREACH_WORKER": "off", "CHRONOS_E2E_REFUSED_LOG": str(log), "CHRONOS_E2E_GUARD_PROBE": "1"}
    proc = subprocess.Popen([sys.executable, "-m", "tests.e2e_server", "--host", "127.0.0.1", "--port", str(port)],
                            cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        with time_limit(60), httpx.Client(timeout=15) as client:
            for _ in range(300):  # 뜰 때까지(최대 약 30초)
                try:
                    if client.get(f"{base}/api/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert proc.poll() is None, "감싸개 서버가 뜨지 못하고 끝났습니다"
                time.sleep(0.1)
            r = client.get(f"{base}/__e2e/guard-probe")
        assert r.status_code == 200, r.text
        got = r.json()
        assert got["loop"].startswith("asyncio."), got  # uvloop 가 아니다
        assert got["open_connection"] == "ConnectionRefusedError", got  # 연결하지 못했다
        assert got["httpx"] == "ConnectError", got  # httpx 는 ConnectionRefusedError 를 ConnectError 로 감싼다
        lines = log.read_text(encoding="utf-8").splitlines()
        assert len(lines) >= 2 and all(line.endswith("getaddrinfo example.invalid") for line in lines), lines
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
