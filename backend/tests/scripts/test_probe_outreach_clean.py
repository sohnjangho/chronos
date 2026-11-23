"""Task 59 — 실측 스크립트(터미널 껍데기). 실제 제공사를 부르지 않는다(httpx.MockTransport).

단계 함수 자체의 시험은 tests/notify/test_diagnostics.py. 여기는 환경 변수·--send·찍는 글만 본다.
"""

import httpx

from scripts.probe_outreach import Probe, run
from tests.notify.test_diagnostics import (
    ACCOUNT,
    FROM,
    LEAKS,
    SENTINEL_KEY,
    SENTINEL_PHONE,
    TO,
    KatFake,
)

ENV = {"KAT_API_KEY": SENTINEL_KEY, "KAT_ACCOUNT_ID": ACCOUNT, "KAT_FROM": FROM, "PROBE_TO": TO}


def set_env(monkeypatch, env: dict[str, str] | None) -> None:
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in (env or {}).items():
        monkeypatch.setenv(name, value)


async def no_sleep(_s: float) -> None:
    return None


def assert_clean(text: str) -> None:
    for leak in LEAKS:
        assert leak not in text, leak


def test_probe_output_is_scrubbed():
    p = Probe(secrets=[SENTINEL_KEY, "AC00000000003c4d"], numbers=["01000000199"])
    out = p.clean(f"key={SENTINEL_KEY} acct=AC00000000003c4d to=010-0000-0199 raw=01000000199")
    assert SENTINEL_KEY not in out and "3c4d" not in out and "0199" not in out


def test_missing_env_skips_without_request(monkeypatch, capsys):
    set_env(monkeypatch, None)
    fake = KatFake()
    code, p = run(["--send"], transport=fake, sleep=no_sleep)
    out = capsys.readouterr().out
    assert code == 1 and p.sent == 0 and fake.requests == []
    for step in ("P1", "P2", "P3", "P4"):
        assert f"[{step}] SKIP" in out


def test_send_steps_need_flag(monkeypatch, capsys):
    set_env(monkeypatch, ENV)
    fake = KatFake()
    code, p = run(["--steps", "2"], transport=fake, sleep=no_sleep)
    out = capsys.readouterr().out
    assert "[P2] SKIP — --send 필요" in out
    assert p.sent == 0 and fake.requests == [] and code == 0


def test_full_run_prints_ok_lines_and_no_secret(monkeypatch, capsys):
    set_env(monkeypatch, ENV)
    fake = KatFake(statuses=("queued", "sent"))
    code, p = run(["--send"], transport=fake, sleep=no_sleep)
    out = capsys.readouterr().out
    assert code == 0, out
    for step in ("P1", "P2", "P3", "P4"):
        assert f"[{step}] OK — " in out
    assert "queued → sent" in out and "구조:" in out
    assert_clean(out)
    assert p.sent == len(fake.requests) == 5
    assert len([r for r in fake.requests if r.method == "POST"]) == 1


def test_still_queued_is_a_fail_line(monkeypatch, capsys):
    set_env(monkeypatch, ENV)
    code, p = run(["--send"], transport=KatFake(statuses=("queued",)), sleep=no_sleep)
    out = capsys.readouterr().out
    assert "[P3] FAIL — still_queued" in out and code == 1 and p.sent == 7


def test_error_and_network_failures_print_no_secret(monkeypatch, capsys):
    set_env(monkeypatch, ENV)
    fake = KatFake(override=lambda r: httpx.Response(401, json={
        "code": "unauthorized", "error": f"bad key {SENTINEL_KEY} for {ACCOUNT} from {FROM} to {SENTINEL_PHONE}"}))
    code, _ = run(["--steps", "1"], transport=fake, sleep=no_sleep)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url} key {SENTINEL_KEY}")

    code2, _ = run(["--steps", "4"], transport=KatFake(override=boom), sleep=no_sleep)
    out = capsys.readouterr().out
    assert "[P1] FAIL — unauthorized" in out and "[P4] FAIL — ConnectError" in out and code == code2 == 1
    assert "cannot reach" not in out
    assert_clean(out)


def test_send_without_recipient_is_a_fail_line(monkeypatch, capsys):
    set_env(monkeypatch, {k: v for k, v in ENV.items() if k != "PROBE_TO"})
    fake = KatFake()
    code, _ = run(["--send", "--steps", "2"], transport=fake, sleep=no_sleep)
    out = capsys.readouterr().out
    assert code == 1 and "[P2] FAIL — " in out and "PROBE_TO" in out and fake.requests == []
