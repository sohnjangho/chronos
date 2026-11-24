"""모래상자 자식 프로세스(Task 98): `python -m app.outreach.scenarios.prove` 가 격자 칸 하나를 진짜 하네스로 돌린다.

시험은 서버가 띄우는 것과 같은 새 프로세스로 돌린다(이 프로세스에는 pytest 가 불려 있어 울타리를 볼 수 없다).
자식 환경은 서버가 주는 꼴 그대로 — 모래상자 변수 · 새 임시 data 폴더 · 비밀 없음.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.outreach.scenarios import prove
from app.outreach.scenarios.drive_text import NUMBERS
from app.outreach.scenarios.grid import CHANNEL_ONLY
from app.outreach.scenarios.situations import COLUMNS, SITUATIONS

BACKEND = Path(__file__).resolve().parents[3]
PHONE = re.compile(r"0\d{1,2}[-\s.]?\d{3,4}[-\s.]?\d{4}")


def _child(tmp_path: Path, *args: str, sandbox: bool = True) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TMPDIR": str(tmp_path), "CHRONOS_DATA_DIR": str(tmp_path / "data"),
           "CHRONOS_QDRANT_URL": "", "CHRONOS_OUTREACH_WORKER": "off"}
    if sandbox:
        env["CHRONOS_HARNESS_SANDBOX"] = "1"
    return subprocess.run([sys.executable, "-E", "-s", "-m", "app.outreach.scenarios.prove", *args], check=False, cwd=BACKEND,
                          env=env, capture_output=True, text=True, timeout=60)


def _out(done: subprocess.CompletedProcess) -> dict:
    assert done.returncode == 0, done.stderr[-2000:]
    lines = done.stdout.strip().splitlines()
    assert len(lines) == 1  # JSON 한 줄뿐
    return json.loads(lines[0])


def test_refuses_without_the_sandbox_variable(tmp_path):
    done = _child(tmp_path, "S-01@sms_in", sandbox=False)
    assert done.returncode == 2 and done.stdout == ""
    assert "CHRONOS_HARNESS_SANDBOX" in done.stderr


def test_rule_ids_name_one_cell_or_one_channel_case():
    assert prove.parse("S-07@call_in") == ("cell", "S-07", "call_in")
    assert prove.parse("C-V1") == ("case", "voicemail", "call_out")
    assert prove.parse("C-S3") == ("case", "photo", "sms_in")
    assert prove.parse("C-K2") == ("case", "kakao_fell_back", "sms_reply")
    for bad in ("S-07", "S-99@call_in", "S-24@call_in", "S-07@fax", "C-V9", "C-X1", "H-CPM-01", "S-07@call_in;rm"):
        with pytest.raises(ValueError):
            prove.parse(bad)  # 표에 없는 칸(S-24 전화 받기는 「—」)·모양이 틀린 id


def test_case_ids_follow_the_channel_only_list():
    ids = prove.case_ids()
    assert sorted(ids) == ["C-K1", "C-K2", "C-S1", "C-S2", "C-S3", "C-V1", "C-V2", "C-V3", "C-V4", "C-V5"]
    assert sorted(ids.values()) == sorted(case.id for case in CHANNEL_ONLY)


def test_layout_is_the_design_table(tmp_path):
    layout = _out(_child(tmp_path, "--layout"))
    assert layout["columns"] == list(COLUMNS)
    assert [r["id"] for r in layout["rows"]] == [f"S-{n:02d}" for n in range(1, 25)]
    for row, situation in zip(layout["rows"], SITUATIONS, strict=True):
        assert set(row["cells"]) == set(COLUMNS) and row["title"] == situation.title
        for column, cell in row["cells"].items():
            assert cell["mark"] == situation.marks[column]
            assert cell["runnable"] == (situation.marks[column] != "none")
            assert cell["guard"] == situation.guards.get(column)
            assert cell["note"] == situation.notes.get(column)
    media = [c["medium"] for c in layout["channel_only"]]
    assert (media.count("call"), media.count("sms"), media.count("kakao")) == (5, 3, 2)
    kinds = {(r["id"], c): cell["note_kind"] for r in layout["rows"] for c, cell in r["cells"].items() if cell["note"]}
    assert {k for k, kind in kinds.items() if kind == "diverged"} == {
        ("S-04", "call_out"), ("S-04", "call_in"), ("S-13", "call_out"), ("S-13", "call_in"), ("S-20", "call_in")}
    assert kinds[("S-21", "call_in")] == "simulated" and kinds[("S-10", "sms_in")] == "common_only"
    assert kinds[("S-01", "sms_in")] == "design_diff"


def test_cell_passes_and_broken_guard_fails_in_the_child(tmp_path):
    held = _out(_child(tmp_path, "S-22@call_out"))
    assert held["passed"] is True and held["broken_guard"] is None and held["checks"]
    assert any(e["rule"] == "recheck_before_dial" for e in held["events"])
    broken = _out(_child(tmp_path, "S-22@call_out", "--broken"))
    assert broken["passed"] is False and broken["broken_guard"] == "gate.test_mode"
    assert [c["ok"] for c in broken["checks"] if c["guarded"]] and not all(c["ok"] for c in broken["checks"] if c["guarded"])


def test_cell_without_a_guard_refuses_broken_run(tmp_path):
    done = _child(tmp_path, "S-10@call_out", "--broken")
    assert done.returncode == 3 and json.loads(done.stdout)["error"] == "no_guard"


def test_output_has_no_phone_number(tmp_path):
    raw = _child(tmp_path, "S-02@sms_in").stdout  # 대본의 상대가 번호(010-0000-0144)를 불러 준다
    assert json.loads(raw)["passed"] is True
    digits = [n for n in NUMBERS.values() if n]
    assert not any(n in raw for n in digits) and not PHONE.search(raw)


def test_divergent_and_simulated_cells_carry_their_note(tmp_path):
    diverged = _out(_child(tmp_path, "S-20@call_in"))  # 대본의 되풀이는 통화 한 통 — 같은 대본으로는 통과하지 않는다
    assert diverged["passed"] is False and diverged["note"].startswith("하네스가 갈라짐")
    simulated = _out(_child(tmp_path, "C-V3"))  # silence — 코드가 시킨 말은 가짜에서만 들린다
    assert simulated["passed"] is True and simulated["note"].startswith("가짜에서만")


def test_output_is_capped():
    big = {"passed": True, "checks": [], "events": [{"rule": "delivery", "detail": "가" * 500}] * 5000, "note": None}
    text = prove.dump(big)
    assert len(text.encode()) <= prove.OUTPUT_CAP and json.loads(text)["events_omitted"] > 0
