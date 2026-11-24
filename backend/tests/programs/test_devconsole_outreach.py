"""개발 콘솔 ⑤(Task 98): 「연락 하네스」 묶음 — 격자(실엔진·가드 확인)·상한·받는 통화.

격자 칸은 **서버 프로세스 밖** 모래상자 자식 프로세스(prove)에서 돈다. 서버는 그 변수를 켜지 않고, 가짜를 끼우지 않고,
문·도구를 무르지 않는다. 자식은 새 임시 data 폴더 · 비밀 없는 환경 · 30초 제한 · 출력 상한. 사람·번호는 모두 가상이다.
"""

import ast
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.outreach.harness import door as door_mod
from app.outreach.harness import events, gate, review, toolsets
from app.outreach.harness.registry import SANDBOX_ENV
from app.outreach.harness.types import GATE_RULES, Ref
from app.programs.devconsole import outreach_catalog
from app.security.crypto import encrypt
from app.security.passwords import hash_password
from app.security.tokens import issue_token
from app.store.tables import User
from app.store.tables_outreach import (
    NotifyConnection,
    OutreachCall,
    OutreachMessage,
    OutreachUsage,
)
from tests.helpers import auth
from tests.outreach_doubles import SENTINEL_DIGITS, SENTINEL_KEY

BACKEND = Path(__file__).resolve().parents[2]
DEVCONSOLE = BACKEND / "app" / "programs" / "devconsole"
FRONT = BACKEND.parent / "frontend" / "src" / "programs" / "devconsole"
PHONE = re.compile(r"0\d{1,2}[-\s.]?\d{3,4}[-\s.]?\d{4}")
NOW = datetime.now(UTC)


def _catalog(client, admin) -> dict:
    r = client.get("/api/devconsole/catalog", headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def _run(client, admin, rule_id: str, broken: bool = False) -> dict:
    url = f"/api/devconsole/harness/{rule_id}/test" + ("?broken=1" if broken else "")
    r = client.post(url, headers=admin)
    assert r.status_code == 200, r.text
    return r.json()


def _rows(session) -> dict[str, int]:
    session.expire_all()
    return {t.__tablename__: session.scalar(select(func.count()).select_from(t))
            for t in (OutreachMessage, OutreachCall, NotifyConnection, OutreachUsage, User)}


def test_grid_matches_design_table(client, admin):
    grid = _catalog(client, admin)["outreach_grid"]
    assert [c["key"] for c in grid["columns"]] == ["call_out", "call_in", "sms_in", "sms_reply"]
    assert [c["label"] for c in grid["columns"]] == ["전화 걸기", "전화 받기", "문자 받기", "우리 문자·카카오톡에 온 답"]
    assert [r["id"] for r in grid["rows"]] == [f"S-{n:02d}" for n in range(1, 25)]
    assert all(set(r["cells"]) == {"call_out", "call_in", "sms_in", "sms_reply"} for r in grid["rows"])
    marks = {(r["id"], c): cell["mark"] for r in grid["rows"] for c, cell in r["cells"].items()}
    assert marks[("S-01", "call_out")] == "run" and marks[("S-24", "call_in")] == "none"
    assert sum(cell["runnable"] for r in grid["rows"] for cell in r["cells"].values()) == 86
    media = [c["medium"] for c in grid["channel_only"]]
    assert len(media) == 10 and (media.count("call"), media.count("sms"), media.count("kakao")) == (5, 3, 2)
    assert len(grid["principles"]) == 7
    assert grid["limits_note"] and grid["connection_id"] is None  # 알림 연결이 없으면 상한 칸은 자리만
    s21 = next(r for r in grid["rows"] if r["id"] == "S-21")["cells"]["call_in"]
    assert s21["note_kind"] == "simulated" and s21["note"].startswith("가짜에서만")  # 운영 동작으로 읽히지 않게


def test_cell_runs_real_engine_in_isolation(client, admin, session):
    before = _rows(session)
    body = _run(client, admin, "S-22@sms_reply")
    assert body["engine"] == "live_harness" and body["rule_id"] == "S-22@sms_reply"
    assert body["passed"] is True and body["blocked"] is True and body["broken_guard"] is None
    assert body["checks"] and all({"text", "ok"} <= set(c) for c in body["checks"])
    assert {"title", "elapsed_ms", "simulated_input", "model_feedback"} <= set(body)
    assert set(GATE_RULES.values()) & {e["rule"] for e in body["events"]}
    assert all(e["group_label"] for e in body["events"])
    assert _rows(session) == before  # PM 자료(서버 DB)는 그대로


def test_grid_cells_run_only_in_sandbox_child(client, admin, monkeypatch):
    seen: list[dict] = []
    real = subprocess.Popen

    def spy(args, **kw):
        seen.append({"args": list(args), "env": dict(kw["env"]), "cwd": kw.get("cwd")})
        return real(args, **kw)

    monkeypatch.setattr(outreach_catalog.subprocess, "Popen", spy)
    _run(client, admin, "S-03@sms_in")
    assert SANDBOX_ENV not in os.environ
    child = seen[-1]
    assert "app.outreach.scenarios.prove" in child["args"] and "S-03@sms_in" in child["args"]
    env = child["env"]
    assert env[SANDBOX_ENV] == "1" and env["CHRONOS_QDRANT_URL"] == "" and env["CHRONOS_OUTREACH_WORKER"] == "off"
    assert Path(env["CHRONOS_DATA_DIR"]).resolve() != Path(os.environ["CHRONOS_DATA_DIR"]).resolve()
    assert not Path(env["CHRONOS_DATA_DIR"]).exists()  # 실행이 끝나면 지운다
    assert not ({"CHRONOS_SECRET_KEY", "CHRONOS_ADMIN_PASSWORD", "CHRONOS_ADMIN_ID"} & set(env))  # 비밀 없음
    # 서버 쪽 콘솔 코드는 가짜를 끼우거나 무르기·대본 구동기를 불러오지 않는다
    for path in DEVCONSOLE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
                {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | \
                  {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert "pinned" not in names, path.name
        assert not any(m.startswith("app.outreach.scenarios") for m in imports), path.name


def _gate_places() -> dict[str, object]:
    return {"gate._barred": gate._barred, "gate._working": gate._working, "gate._over_limit": gate._over_limit,
            "gate._mode": gate._mode, "gate._twin": gate._twin, "door.resolve": door_mod.resolve,
            "door.admit": door_mod.admit, "review.check": review.check, "toolsets.for_class": toolsets.for_class}


def test_broken_guard_makes_cell_fail_in_child_process():
    places = _gate_places()
    broken = outreach_catalog.run("S-22@call_out", broken=True)
    assert broken["broken_guard"] == "gate.test_mode" and broken["passed"] is False and broken["guard_confirmed"] is True
    assert _gate_places() == places  # 부모 프로세스의 문은 그대로
    again = outreach_catalog.run("S-22@call_out")
    assert again["passed"] is True and again["guard_confirmed"] is None


def test_guard_is_not_confirmed_when_the_cell_fails_without_breaking():
    """그냥 돌려도 실패하는 칸(갈라진 칸 등)은 무르니 실패해도 증거가 아니다 — 확인됨이 아니라 null + 까닭."""
    body = outreach_catalog.run("S-20@call_in", broken=True)  # 대본의 되풀이 — 같은 대본으로는 통과하지 않음
    assert body["baseline_passed"] is False and body["guard_confirmed"] is None
    assert body["guard_reason"] == outreach_catalog.BASELINE_FAILS


@pytest.mark.parametrize(("baseline", "broken", "want"), [
    ([True, True], [False, True], True),  # 그냥은 통과 · 무르니 지키는 곳 기대가 거짓
    ([True, True], [True, True], False),  # 물러도 통과 — 시험이 엔진을 보지 않음
    ([True, True], [True, False], False),  # 지키는 곳 기대가 아닌 것만 거짓 — 가드의 증거 아님
    ([False, True], [False, True], None),  # 그냥 돌려도 실패 — 확인할 수 없음
])
def test_guard_verdict_needs_a_passing_baseline_and_a_guarded_failure(baseline, broken, want):
    def checks(oks):
        return [{"text": f"기대 {i}", "ok": ok, "guarded": i == 0} for i, ok in enumerate(oks)]

    body = {"passed": all(broken), "checks": checks(broken), "baseline": {"passed": all(baseline), "checks": checks(baseline)}}
    assert outreach_catalog.guard_verdict(body)[0] is want


def test_broken_run_never_patches_server_process(monkeypatch):
    import sys

    # 서버 프로세스에서 무르기를 불러오려 하면 바로 터지게 — 그래도 가드 끄고 돌리기가 되면 자식에서 돈 것이다
    monkeypatch.setitem(sys.modules, "app.outreach.scenarios.breaks", None)
    places = _gate_places()
    body = outreach_catalog.run("S-07@sms_in", broken=True)
    assert body["broken_guard"] == "tools.scope" and body["passed"] is False
    assert _gate_places() == places and SANDBOX_ENV not in os.environ


def test_run_output_has_no_number(client, admin):
    body = _run(client, admin, "S-02@call_in")  # 상대가 통화로 번호를 불러 준다
    raw = json.dumps(body, ensure_ascii=False)
    assert body["passed"] is True
    assert "01000000144" not in raw and "0000-0144" not in raw and not PHONE.search(raw)


def test_bad_rule_ids_are_404_and_no_child_starts(client, admin, monkeypatch):
    _catalog(client, admin)  # 격자 모양(자식 하나)을 먼저 읽어 둔다 — 그 뒤로는 칸을 자식 없이 거른다
    monkeypatch.setattr(outreach_catalog.subprocess, "Popen", lambda *a, **k: pytest.fail("자식을 띄움"))
    for bad in ("S-99@call_in", "S-24@call_in", "S-07@fax", "C-V9", "S-07%40call_in%3Brm"):
        assert client.post(f"/api/devconsole/harness/{bad}/test", headers=admin).status_code == 404
    r = client.post("/api/devconsole/harness/S-10@call_out/test?broken=1", headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "no_guard"  # 지키는 곳이 없는 칸(공통 겹만)
    r = client.post("/api/devconsole/harness/H-CPM-01/test?broken=1", headers=admin)
    assert r.status_code == 422 and r.json()["code"] == "not_supported"  # 다른 규칙에는 무르기 길이 없다


def test_child_is_killed_after_the_time_limit(monkeypatch):
    outreach_catalog._layout_once()  # 격자 모양은 먼저(진짜 자식으로) 읽어 둔다
    monkeypatch.setattr(outreach_catalog, "TIMEOUT_S", 0.5)
    monkeypatch.setattr(outreach_catalog, "_command", lambda args: [outreach_catalog.sys.executable, "-c",
                                                                     "import time; time.sleep(30)"])
    with pytest.raises(outreach_catalog.ApiError) as caught:
        outreach_catalog.run("S-01@sms_in")
    assert caught.value.status_code == 504 and caught.value.code == "sandbox_timeout"


def test_child_error_line_is_502_even_with_exit_zero(monkeypatch):
    outreach_catalog._layout_once()
    monkeypatch.setattr(outreach_catalog, "_command", lambda args: [outreach_catalog.sys.executable, "-c",
                                                                     "print('{\"error\": \"too_large\"}')"])
    with pytest.raises(outreach_catalog.ApiError) as caught:
        outreach_catalog.run("S-01@sms_in")
    assert caught.value.status_code == 502 and caught.value.code == "sandbox_failed"


def test_timeout_kills_the_whole_process_group(monkeypatch, tmp_path):
    outreach_catalog._layout_once()
    pid_file = tmp_path / "grandchild"
    code = ("import subprocess, sys, time\n"
            f"p = subprocess.Popen(['sleep', '30'])\nopen({str(pid_file)!r}, 'w').write(str(p.pid))\ntime.sleep(30)\n")
    monkeypatch.setattr(outreach_catalog, "TIMEOUT_S", 1.0)
    monkeypatch.setattr(outreach_catalog, "_command", lambda args: [outreach_catalog.sys.executable, "-c", code])
    t0 = time.monotonic()
    with pytest.raises(outreach_catalog.ApiError):
        outreach_catalog.run("S-01@sms_in")
    assert time.monotonic() - t0 < 10  # 손자가 출력 관을 쥐고 있어도 서버가 붙잡히지 않는다
    grandchild = int(pid_file.read_text())
    for _ in range(50):  # 묶음째 죽였으면 곧 사라진다(고아는 init 이 거둔다)
        try:
            os.kill(grandchild, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(grandchild, 9)
        pytest.fail("손자 프로세스가 살아 있음")


def test_child_output_over_the_cap_is_refused(monkeypatch):
    outreach_catalog._layout_once()  # 격자 모양은 먼저(진짜 자식으로) 읽어 둔다
    monkeypatch.setattr(outreach_catalog, "_command", lambda args: [outreach_catalog.sys.executable, "-c",
                                                                     "import sys; sys.stdout.write('x' * 400000)"])
    with pytest.raises(outreach_catalog.ApiError) as caught:
        outreach_catalog.run("S-01@sms_in")
    assert caught.value.code == "sandbox_output"


def test_children_are_bounded(monkeypatch):
    outreach_catalog._layout_once()  # 격자 모양은 먼저(진짜 자식으로) 읽어 둔다
    held = [outreach_catalog._children.acquire(blocking=False) for _ in range(outreach_catalog.MAX_CHILDREN)]
    try:
        assert all(held)
        with pytest.raises(outreach_catalog.ApiError) as caught:
            outreach_catalog.run("S-01@sms_in")
        assert caught.value.status_code == 429
    finally:
        for _ in held:
            outreach_catalog._children.release()


def test_limits_shown_and_edited_through_notify_api_only(client, admin, session):
    conn = NotifyConnection(name="기본 연결", base_url="https://kat.invalid", secret_ciphertext=encrypt(SENTINEL_KEY),
                            secret_last4="9999", account_id="ACCT-0000", sender_number=SENTINEL_DIGITS, is_default=True,
                            status="ok", checked_at=NOW)
    session.add(conn)
    session.commit()
    assert _catalog(client, admin)["outreach_grid"]["connection_id"] == conn.id
    # 콘솔(서버)에는 상한을 쓰는 코드가 없다 — 상한은 알림 연결 API(notify_settings)가 한 곳에서 지킨다
    for path in DEVCONSOLE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "limits_json":
                assert not isinstance(getattr(node, "ctx", None), ast.Store), path.name
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("app.programs.notify_settings"), path.name
    # 화면: 격자가 부르는 상한 길은 공용 LimitsForm(/api/notify/connections/{id}/limits) 뿐
    grid = (FRONT / "OutreachGrid.tsx").read_text(encoding="utf-8")
    assert "shared/outreach/LimitsForm" in grid and "/api/" not in grid
    assert "/limits" not in (FRONT / "devApi.ts").read_text(encoding="utf-8")  # 콘솔 API 에 상한 길이 없다


def _in_call(session, status: str, verdict: str, reason: str) -> int:
    row = OutreachCall(direction="in", origin="peer", origin_name="모르는 번호", caller_class="unknown", status=status,
                       created_at=NOW)
    session.add(row)
    session.commit()
    events.record(session, Ref("call", row.id), "admission", verdict, reason)
    session.commit()
    return row.id


def test_inbound_call_branches_light_only_from_rows(client, admin, session):
    def lit(call_id: int) -> list[str]:
        r = client.get(f"/api/devconsole/outreach/call/{call_id}", headers=admin)
        assert r.status_code == 200, r.text
        return r.json()["branches_lit"]

    assert lit(_in_call(session, "completed", "allowed", "known_caller")) == ["call_answered"]
    assert lit(_in_call(session, "in_call", "allowed", "known_caller")) == []  # 아직 통화 중 — 끝나야 켜진다
    assert lit(_in_call(session, "rejected", "blocked", "blocked_number")) == ["call_rejected"]
    assert lit(_in_call(session, "missed", "noted", "line_busy")) == []  # 받지 못함(통화 중 한도)은 거절이 아니다
    bare = OutreachCall(direction="in", origin="peer", origin_name="모르는 번호", status="completed", created_at=NOW)
    session.add(bare)
    session.commit()
    assert lit(bare.id) == []  # 받기 판정 사건이 없으면 가지도 없다


def test_usage_counts_answered_and_rejected_calls(client, admin, session):
    _in_call(session, "completed", "allowed", "known_caller")
    _in_call(session, "rejected", "blocked", "outside_test")
    calls = client.get("/api/devconsole/usage", headers=admin).json()["outreach"]["calls"]
    assert (calls["calls_answered"], calls["calls_rejected"]) == (1, 1)


def test_admin_only(client, user, session):
    field_user = User(login_id="field1", name="현장 관리자", role="field", password_hash=hash_password("field-pass"))
    session.add(field_user)
    session.commit()
    field = auth(issue_token(field_user.id))
    for who in (user, field):
        assert client.post("/api/devconsole/harness/S-01@sms_in/test", headers=who).status_code == 403
        assert client.post("/api/devconsole/harness/S-01@sms_in/test?broken=1", headers=who).status_code == 403
        assert client.get("/api/devconsole/catalog", headers=who).status_code == 403
