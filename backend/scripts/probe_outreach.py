"""한국AI통신 REST 실측(계획 4 Task 59, 0단계 P1~P4)을 터미널에서 돌리는 얇은 껍데기. 앱의 「연결 진단」과 같은 함수
(`app/notify/diagnostics.py`)를 부르고 결과를 찍는다. 단계·문서 출처·지우는 규칙은 그 모듈 머리 주석에 있다.

사용(저장소 폴더에서. 키·번호는 환경 변수로만 받는다 — 명령줄 인자로 받지 않는다):
    backend/.venv/bin/python backend/scripts/probe_outreach.py                 # P1·P4 (보내지 않음)
    backend/.venv/bin/python backend/scripts/probe_outreach.py --send          # P1~P4 (문자 1건)
    backend/.venv/bin/python backend/scripts/probe_outreach.py --steps 1       # 고른 단계만

- 환경 변수: `KAT_API_KEY`, `KAT_ACCOUNT_ID`(모든 단계), `KAT_FROM`(발신번호) · `PROBE_TO`(PM 본인 번호)(P2).
  없으면 그 단계는 SKIP. 셸 기록에 남지 않게 `read -rs` 로 넣는다.
- 끝 줄: 단계마다 `[P2] OK — …` / `[P2] FAIL — <code> · <까닭>` / `[P2] SKIP — <까닭>`(고르지 않은 단계는 찍지 않는다).
  P3 이 끝까지 접수 상태면(`still_queued`) 여기서는 FAIL 로 찍는다. 종료 코드: FAIL 이 있거나 키·Account ID 가 없으면 1. 요청 상한 8번, 문자 1건. 앱 DB·data/ 는 건드리지 않는다.
"""

import argparse
import asyncio
import os
import sys
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 앱 패키지(app)를 찾게 한다

from app.notify.diagnostics import (
    DEFAULT_BASE_URL,
    LABELS,
    Calls,
    DiagnosticConn,
    DiagnosticStep,
    make_client,
    run_checks,
    scrub,
)


class Skip(Exception):
    """이 단계는 돌리지 않는다(까닭은 글)."""


class StepFail(Exception):
    """이 단계는 실패(글은 짧은 코드)."""


class Note:
    text = ""


class Probe:
    """찍는 쪽. `clean` 은 앱 모듈의 `scrub` 과 같다. `sent` 는 요청 수."""

    def __init__(self, secrets: list[str], numbers: list[str]) -> None:
        self._secrets, self._numbers = secrets, numbers
        self.calls = Calls()
        self.failed = False

    @property
    def sent(self) -> int:
        return self.calls.sent

    def clean(self, text: object, limit: int = 200) -> str:
        return scrub(text, secrets=self._secrets, numbers=self._numbers, limit=limit)

    @contextmanager
    def step(self, code: str, title: str) -> Iterator[Note]:
        """단계 하나. 끝에 OK·FAIL·SKIP 한 줄을 찍는다. 예외는 종류만."""
        print(f"\n{code} {title}")
        note = Note()
        try:
            yield note
        except Skip as e:
            print(f"[{code}] SKIP — {self.clean(e)}")
        except StepFail as e:
            self.failed = True
            print(f"[{code}] FAIL — {self.clean(e)}")
        except Exception as e:  # noqa: BLE001 — 글에 주소·키가 있을 수 있어 종류만 찍는다
            self.failed = True
            print(f"[{code}] FAIL — {type(e).__name__}")
        else:
            print(f"[{code}] OK — {self.clean(note.text)}")

    def show(self, result: DiagnosticStep) -> None:
        """진단 결과 하나를 찍는다(글은 이미 지워져 있지만 한 번 더 지운다)."""
        with self.step(result.id, result.label) as note:
            for line in result.notes:
                print("    " + self.clean(line, 500))
            if result.skipped:
                raise Skip(result.detail)
            if not result.ok:
                raise StepFail(f"{result.code} · {result.detail}")
            note.text = result.detail + (f" · {result.latency_ms}ms" if result.latency_ms is not None else "")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    def steps(text: str) -> tuple[int, ...]:
        picked = {int(s) for s in text.split(",") if s.strip()}
        if not picked or not picked <= {1, 2, 3, 4}:
            raise argparse.ArgumentTypeError("1~4 가운데 쉼표로")
        return tuple(sorted(picked))

    ap = argparse.ArgumentParser(description="한국AI통신 REST 실측(P1~P4). 키·번호는 환경 변수로만.")
    ap.add_argument("--send", action="store_true", help="P2 에서 PROBE_TO 로 실제 문자 1건을 보낸다")
    ap.add_argument("--steps", type=steps, default=(1, 2, 3, 4), help="예: 1,4")
    return ap.parse_args(argv)


def run(argv: list[str] | None = None, *, transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> tuple[int, Probe]:
    """실측 한 번. (종료 코드, Probe). 시험은 `transport` 에 가짜를 넣는다."""
    args = parse_args(argv)
    key = os.environ.get("KAT_API_KEY", "").strip()
    account = os.environ.get("KAT_ACCOUNT_ID", "").strip()
    sender = os.environ.get("KAT_FROM", "").strip()
    to = os.environ.get("PROBE_TO", "").strip()
    p = Probe(secrets=[key, account], numbers=[sender, to])
    if not key or not account:
        for n in args.steps:
            with p.step(f"P{n}", LABELS[f"P{n}"]):
                raise Skip("KAT_API_KEY·KAT_ACCOUNT_ID 필요")
        print(f"\n요청 수: {p.sent}")
        return 1, p
    conn = DiagnosticConn(base_url=DEFAULT_BASE_URL, key=key, account_id=account, sender=sender, test_to=to)

    async def go() -> list[DiagnosticStep]:
        async with make_client(transport=transport) as http:
            return await run_checks(conn, http, send_test_sms=args.send, steps=args.steps, sleep=sleep, calls=p.calls)

    for result in asyncio.run(go()):
        if result.code == "skipped_not_requested":  # --steps 로 고르지 않은 단계
            continue
        if result.id == "P2" and result.skipped and not args.send:
            result.detail = "--send 필요"
        elif result.id == "P2" and result.skipped:  # --send 를 줬는데 못 보냄 → 실패로
            result.skipped, result.code, result.detail = False, "missing_number", "--send 에는 KAT_FROM·PROBE_TO 가 모두 필요"
        p.show(result)
    print(f"\n요청 수: {p.sent}")
    return (1 if p.failed else 0), p


def main() -> int:
    return run(sys.argv[1:])[0]


if __name__ == "__main__":
    sys.exit(main())
