"""Exercise the shell-free shiv recipe without running uv or downloading packages."""

import ast
from importlib.resources import files
from pathlib import Path
import re
import struct
import subprocess
import sys
import textwrap
import zipapp
import zipfile

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
def test_shiv_creates_dist_and_builds_pyz_and_windows_pe_exe(
    shiv_recipe, tmp_path, monkeypatch, dist_exists,
):
    _, body = shiv_recipe
    workspace = tmp_path / "repository with spaces"
    workspace.mkdir()
    src = workspace / "pkg"
    src.mkdir()
    (src / "__main__.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    monkeypatch.chdir(workspace)
    if dist_exists:
        Path("dist").mkdir()
        Path("dist/keep.txt").write_text("keep", encoding="utf-8")
    calls = []

    def run(command, **kwargs):
        assert Path("dist").is_dir()
        zipapp.create_archive(
            src,
            target=Path("dist/te.pyz"),
            interpreter="/usr/bin/env python3",
        )
        calls.append((command, kwargs))

    monkeypatch.setattr(subprocess, "run", run)
    exec(body, {})

    assert calls == [(
        [sys.executable, "-m", "shiv", "-c", "te", "-o", "dist/te.pyz", "."],
        {"check": True},
    )]
    if dist_exists:
        assert Path("dist/keep.txt").read_text(encoding="utf-8") == "keep"

    launcher = files("pip._vendor.distlib").joinpath("t64.exe").read_bytes()
    pyz = Path("dist/te.pyz").read_bytes()
    exe = Path("dist/te.exe").read_bytes()

    assert exe.startswith(b"MZ")
    pe_offset = int.from_bytes(exe[0x3C:0x40], "little")
    assert exe[pe_offset : pe_offset + 4] == b"PE\x00\x00"
    assert exe == launcher + pyz

    eocd = exe.rfind(b"PK\x05\x06")
    cd_size, cd_offset = struct.unpack_from("<II", exe, eocd + 12)
    shebang_offset = eocd - (cd_size + cd_offset)
    assert shebang_offset == len(launcher)
    assert exe[shebang_offset:].startswith(b"#!/usr/bin/env python3\n")

    with zipfile.ZipFile(Path("dist/te.exe")) as zf:
        assert "__main__.py" in zf.namelist()


def test_shiv_build_failure_is_not_ignored(shiv_recipe, tmp_path, monkeypatch):
    _, body = shiv_recipe
    monkeypatch.chdir(tmp_path)

    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(23, command)

    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError) as exc:
        exec(body, {})
    assert exc.value.returncode == 23
    assert not Path("dist/te.exe").exists()
