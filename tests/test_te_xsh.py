"""Exercise the xonsh launcher's interpreter selection without running TE itself."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


LAUNCHER = Path(__file__).resolve().parents[1] / "plugin" / "scripts" / "te.xsh"
pytestmark = pytest.mark.skipif(
    os.name == "nt" or importlib.util.find_spec("xonsh") is None,
    reason="requires xonsh and POSIX executable-script fixtures",
)


@pytest.fixture
def _interpreter():
    def make(path, status, probe_status=0):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            f"if sys.argv[1:3] == ['-E', '-S']: sys.exit({probe_status})\n"
            "Path(os.environ['TE_TEST_RECORD']).write_text(json.dumps({\n"
            "    'args': sys.argv[1:], 'utf8': os.environ.get('PYTHONUTF8'),\n"
            "}))\n"
            f"sys.exit({status})\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
        return path
    return make


def _run(tmp_path, python, windows, isolated=False):
    env = dict(os.environ, TE_TEST_RECORD=str(tmp_path / "record.json"))
    env.pop("TE_PYTHON", None)
    env.pop("OS", None)
    env["PATH"] = str(tmp_path / "bin") + ("" if isolated else os.pathsep + env.get("PATH", ""))
    if python is not None:
        env["TE_PYTHON"] = str(python)
    if windows:
        env["OS"] = "Windows_NT"
    return subprocess.run(
        [sys.executable, "-m", "xonsh", "--no-rc", str(LAUNCHER), "config", "show", "a b"],
        env=env, capture_output=True, text=True, timeout=20,
    )


@pytest.mark.parametrize("windows", [False, True])
def test_explicit_python_bypasses_discovery(tmp_path, windows, _interpreter):
    # Even a WindowsApps path must be trusted when explicitly selected.
    python = _interpreter(tmp_path / "WindowsApps" / "custom python", 37)
    _interpreter(tmp_path / "bin" / "python3", 99)

    result = _run(tmp_path, python, windows)

    assert result.returncode == 37, result.stderr
    assert json.loads((tmp_path / "record.json").read_text()) == {
        "args": [str(LAUNCHER.with_name("te_bootstrap.py")), "cli", "config", "show", "a b"],
        "utf8": "1",
    }


@pytest.mark.parametrize("windows", [False, True])
def test_invalid_explicit_python_does_not_fall_back(tmp_path, windows, _interpreter):
    _interpreter(tmp_path / "bin" / "python3", 99)

    result = _run(tmp_path, tmp_path / "missing-python", windows)

    assert result.returncode != 0
    assert not (tmp_path / "record.json").exists()


@pytest.mark.parametrize("python", [None, ""])
@pytest.mark.parametrize("windows", [False, True])
def test_unset_or_empty_python_keeps_discovery(tmp_path, python, windows, _interpreter):
    _interpreter(tmp_path / "bin" / "python3", 23)

    result = _run(tmp_path, python, windows)

    assert result.returncode == 23, result.stderr


def test_discovery_skips_old_and_unusable_python(tmp_path, _interpreter):
    _interpreter(tmp_path / "bin" / "python3", 21, probe_status=1)
    _interpreter(tmp_path / "bin" / "python3.15", 22, probe_status=127)
    _interpreter(tmp_path / "bin" / "python3.10", 23)

    result = _run(tmp_path, None, False, isolated=True)

    assert result.returncode == 23, result.stderr


def test_discovery_falls_back_to_first_old_python(tmp_path, _interpreter):
    _interpreter(tmp_path / "bin" / "python3", 23, probe_status=1)
    _interpreter(tmp_path / "bin" / "python3.15", 22, probe_status=1)
    _interpreter(tmp_path / "bin" / "python3.10", 21, probe_status=127)

    result = _run(tmp_path, None, False, isolated=True)

    assert result.returncode == 23, result.stderr


def test_discovery_reports_no_usable_python(tmp_path, _interpreter):
    _interpreter(tmp_path / "bin" / "python3", 21, probe_status=127)

    result = _run(tmp_path, None, False, isolated=True)

    assert result.returncode == 1
    assert "no python3 on PATH" in result.stderr
