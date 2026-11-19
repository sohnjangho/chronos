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


def test_domains_python_is_checked(tmp_path):
    f = tmp_path / "backend/app/domains/loader.py"
    f.parent.mkdir(parents=True)
    f.write_text("a=1\n" * 801)
    r = run(tmp_path)
    assert r.returncode == 1 and "loader.py" in r.stdout


def test_domains_yaml_is_not_checked(tmp_path):
    f = tmp_path / "backend/app/domains/construction/pack.yaml"
    f.parent.mkdir(parents=True)
    f.write_text("a: 1\n" * 2000)
    assert run(tmp_path).returncode == 0


def test_tests_folder_under_scanned_root_is_excluded(tmp_path):
    f = tmp_path / "backend/app/tests/t.py"
    f.parent.mkdir(parents=True)
    f.write_text("a=1\n" * 2000)
    assert run(tmp_path).returncode == 0


def long_function(name, body_lines):
    return f"def {name}():\n" + "    a = 1\n" * body_lines


def test_function_over_hard_limit_fails(tmp_path):
    f = tmp_path / "backend/app/f.py"
    f.parent.mkdir(parents=True)
    f.write_text(long_function("long_fn", 100))  # 101줄
    r = run(tmp_path)
    assert r.returncode == 1 and "long_fn" in r.stdout


def test_function_over_soft_limit_warns_only(tmp_path):
    f = tmp_path / "backend/app/f.py"
    f.parent.mkdir(parents=True)
    f.write_text(long_function("long_fn", 50))  # 51줄
    r = run(tmp_path)
    assert r.returncode == 0 and "long_fn" in r.stdout


def test_long_function_in_excluded_path_passes(tmp_path):
    f = tmp_path / "backend/app/tests/f.py"
    f.parent.mkdir(parents=True)
    f.write_text(long_function("long_fn", 200))
    assert run(tmp_path).returncode == 0


def test_long_function_in_domains_fails(tmp_path):
    f = tmp_path / "backend/app/domains/f.py"
    f.parent.mkdir(parents=True)
    f.write_text(long_function("long_fn", 100))
    r = run(tmp_path)
    assert r.returncode == 1 and "long_fn" in r.stdout
