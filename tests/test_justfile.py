"""Exercise the shell-free shiv recipe without running uv or downloading packages."""

import ast
from importlib.resources import files
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import textwrap
import venv
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


@pytest.fixture(params=[False, True], ids=["new-dist", "existing-dist"])
def shiv_artifacts(shiv_recipe, tmp_path, monkeypatch, request):
    dist_exists = request.param
    _, body = shiv_recipe
    workspace = tmp_path / "repository with spaces"
    workspace.mkdir()
    src = workspace / "pkg"
    src.mkdir()
    (src / "__main__.py").write_text("print('launcher-ok')\n", encoding="utf-8")
    (src / "data.bin").write_bytes(bytes(range(256)))
    monkeypatch.chdir(workspace)
    if dist_exists:
        Path("dist").mkdir()
        Path("dist/keep.txt").write_text("keep", encoding="utf-8")
    calls = []
    original_pyz = []

    def run(command, **kwargs):
        assert Path("dist").is_dir()
        target = Path("dist/te.pyz")
        zipapp.create_archive(
            src,
            target=target,
            interpreter="/usr/bin/env python3",
            compressed=dist_exists,
        )
        with zipfile.ZipFile(target, "a") as archive:
            archive.comment = b"archive metadata"
            info = zipfile.ZipInfo("metadata.txt", date_time=(2024, 2, 3, 4, 5, 6))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.comment = b"member metadata"
            archive.writestr(info, b"preserve me")
        original_pyz.append(target.read_bytes())
        calls.append((command, kwargs))

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "run", run)
        exec(body, {})

    assert calls == [(
        [sys.executable, "-m", "shiv", "-c", "te", "-o", "dist/te.pyz", "."],
        {"check": True},
    )]
    if dist_exists:
        assert Path("dist/keep.txt").read_text(encoding="utf-8") == "keep"

    assert Path("dist/te.pyz").read_bytes() == original_pyz[0]
    return workspace / "dist"


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX permission bits")
def test_shiv_output_has_safe_posix_permissions(shiv_artifacts):
    mode = stat.S_IMODE((shiv_artifacts / "te.exe").stat().st_mode)
    assert mode == 0o755, f"unexpected executable permissions: {oct(mode)}"


def test_shiv_creates_dist_and_builds_pyz_and_windows_pe_exe(shiv_artifacts):
    launcher = files("pip._vendor.distlib").joinpath("t64.exe").read_bytes()
    pyz = (shiv_artifacts / "te.pyz").read_bytes()
    exe_path = shiv_artifacts / "te.exe"
    # Inspect the payload independently of the separate permissions regression.
    exe_path.chmod(exe_path.stat().st_mode | stat.S_IRUSR)
    exe = exe_path.read_bytes()

    assert exe.startswith(b"MZ")
    pe_offset = int.from_bytes(exe[0x3C:0x40], "little")
    assert exe[pe_offset : pe_offset + 4] == b"PE\x00\x00"
    assert exe.startswith(launcher)
    assert pyz.startswith(b"#!/usr/bin/env python3\n")

    eocd = exe.rfind(b"PK\x05\x06")
    cd_size, cd_offset = struct.unpack_from("<II", exe, eocd + 12)
    shebang_offset = eocd - (cd_size + cd_offset)
    assert shebang_offset == len(launcher)
    assert exe[shebang_offset:].startswith(b"#!/usr/bin/env python\n")


def test_shiv_windows_archive_preserves_contents_and_metadata(shiv_artifacts):
    exe_path = shiv_artifacts / "te.exe"
    exe_path.chmod(exe_path.stat().st_mode | stat.S_IRUSR)
    with zipfile.ZipFile(shiv_artifacts / "te.pyz") as pyz, zipfile.ZipFile(exe_path) as exe:
        assert exe.testzip() is None
        assert exe.namelist() == pyz.namelist()
        assert exe.comment == pyz.comment
        for original, rebuilt in zip(pyz.infolist(), exe.infolist()):
            assert exe.read(rebuilt) == pyz.read(original)
            assert rebuilt.compress_type == original.compress_type
            assert rebuilt.date_time == original.date_time
            assert rebuilt.external_attr == original.external_attr
            assert rebuilt.comment == original.comment
            assert rebuilt.extra == original.extra


@pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows execution")
def test_shiv_windows_launcher_runs_with_only_python_exe(shiv_artifacts, tmp_path):
    runtime = tmp_path / "runtime with spaces"
    venv.EnvBuilder(with_pip=False).create(runtime)
    scripts = runtime / "Scripts"
    assert shutil.which("python", path=str(scripts)) is not None
    assert shutil.which("python3", path=str(scripts)) is None
    env = os.environ.copy()
    env["PATH"] = str(scripts)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [str(shiv_artifacts / "te.exe")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "launcher-ok"


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
