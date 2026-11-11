"""Exercise the shell-free shiv recipe without running uv or downloading packages."""

import ast
from pathlib import Path
import re
import subprocess
import sys
import textwrap

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def shiv_recipe():
    source = (ROOT / "justfile").read_text(encoding="utf-8")
    match = re.search(
        r"^\[script\(([^\n]+)\)\]\nshiv:\n((?:[ \t]+[^\n]*\n|\n)+)",
        source,
        re.MULTILINE,
    )
    assert match, "shiv must be a script recipe, not a Unix-shell recipe"
    interpreter = ast.literal_eval(f"[{match[1]}]")
    body = compile(textwrap.dedent(match[2]), "justfile:shiv", "exec")
    return interpreter, body


def test_shiv_interpreter_uses_uv_without_a_shell(shiv_recipe):
    interpreter, _ = shiv_recipe
    assert interpreter == [
        "uv", "run", "--no-project", "--with", "shiv", "--with", "pip", "python",
    ]


@pytest.mark.parametrize("dist_exists", [False, True])
def test_shiv_creates_dist_and_builds_with_the_same_python(
    shiv_recipe, tmp_path, monkeypatch, dist_exists,
):
    _, body = shiv_recipe
    workspace = tmp_path / "repository with spaces"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    if dist_exists:
        Path("dist").mkdir()
        Path("dist/keep.txt").write_text("keep", encoding="utf-8")
    calls = []

    def run(command, **kwargs):
        assert Path("dist").is_dir()
        calls.append((command, kwargs))

    monkeypatch.setattr(subprocess, "run", run)
    exec(body, {})

    assert calls == [(
        [sys.executable, "-m", "shiv", "-c", "te", "-o", "dist/te.pyz", "."],
        {"check": True},
    )]
    if dist_exists:
        assert Path("dist/keep.txt").read_text(encoding="utf-8") == "keep"


def test_shiv_build_failure_is_not_ignored(shiv_recipe, tmp_path, monkeypatch):
    _, body = shiv_recipe
    monkeypatch.chdir(tmp_path)

    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(23, command)

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError) as exc:
        exec(body, {})
    assert exc.value.returncode == 23
