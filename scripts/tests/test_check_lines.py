import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "check_lines.py"


def run(root):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(root)], capture_output=True, text=True
    )


def test_over_hard_limit_fails(tmp_path):
    f = tmp_path / "backend/app/x.py"
    f.parent.mkdir(parents=True)
    f.write_text("a=1\n" * 801)
    assert run(tmp_path).returncode == 1


def test_over_soft_limit_warns_only(tmp_path):
    f = tmp_path / "backend/app/x.py"
    f.parent.mkdir(parents=True)
    f.write_text("a=1\n" * 401)
    r = run(tmp_path)
    assert r.returncode == 0 and "x.py" in r.stdout


def test_tests_are_excluded(tmp_path):
    f = tmp_path / "backend/tests/t.py"
    f.parent.mkdir(parents=True)
    f.write_text("a=1\n" * 2000)
    assert run(tmp_path).returncode == 0


def test_frontend_over_hard_limit_fails(tmp_path):
    f = tmp_path / "frontend/src/os/Big.tsx"
    f.parent.mkdir(parents=True)
    f.write_text("x\n" * 601)
    assert run(tmp_path).returncode == 1


def test_test_and_generated_files_are_excluded(tmp_path):
    d = tmp_path / "frontend/src/os"
    d.mkdir(parents=True)
    (d / "Big.test.tsx").write_text("x\n" * 2000)
    (d / "api.gen.ts").write_text("x\n" * 2000)
    assert run(tmp_path).returncode == 0


def test_domains_are_excluded(tmp_path):
    f = tmp_path / "backend/app/domains/construction/pack.py"
    f.parent.mkdir(parents=True)
    f.write_text("a=1\n" * 2000)
    assert run(tmp_path).returncode == 0
