#!/usr/bin/env xonsh
"""TokenEconomizer command line (`te status`, `te toolprune show`, `te config`, ...).

A xonsh port of `te`: run `te_bootstrap.py cli` under the first Python 3 found, passing the
arguments through. On Windows the Microsoft Store alias under WindowsApps runs nothing, and every
probe of it starts AppXSvc (python/pymanager#396), so a Python outside WindowsApps is tried first
and the alias is probed only as a last resort; `py` is the final candidate.
"""
import os
import sys
from pathlib import Path

from xonsh.procs.executables import locate_executable

# pathlib takes either slash, so a Windows `__file__` with backslashes needs no rewriting.
bootstrap = Path(os.path.abspath(__file__)).parent / "te_bootstrap.py"
windows = ${...}.get("OS") == "Windows_NT"

# Session logs are UTF-8; without this, Python on Windows reads them in the ANSI code page.
$PYTHONUTF8 = "1"


def candidates(*names):
    """$TE_PYTHON when set and non-empty, then `names`."""
    return [name for name in (${...}.get("TE_PYTHON"), *names) if name]


def launcher_flags(name):
    """`py` is the Windows launcher; `-3` asks it for a Python 3."""
    return ["-3"] if name == "py" else []


def outside_windowsapps(name):
    """`name.exe` or `name` in the first $PATH directory outside WindowsApps that has one."""
    for entry in $PATH:
        if not entry or "WindowsApps" in entry:
            continue
        # Join as text: `Path(entry) / name` would drop `entry` for an absolute $TE_PYTHON and
        # hand back the WindowsApps alias itself.
        for path in (Path(f"{entry}/{name}.exe"), Path(f"{entry}/{name}")):
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
    return None


def hand_off(python, *flags):
    """Run the command line under `python` and exit with its status. Never returns."""
    argv = [python, *flags, bootstrap, "cli", *$ARGS[1:]]
    if windows:
        # os.exec* on Windows starts the program and exits at once, so the caller would see
        # this script's status, not the command line's: wait for it and pass its status on.
        sys.exit(![@error_ignore @(argv)].returncode)
    # Replace this process; xexec comes back only when the exec itself failed.
    sys.exit(![@error_ignore xexec @(argv)].returncode)


if windows:
    for name in candidates("python3", "python", "py"):
        python = locate_executable(name)
        if python and "WindowsApps" in python:
            python = outside_windowsapps(name)
        if python:
            hand_off(python, *launcher_flags(name))
    # Only the WindowsApps alias was found: take the first candidate that actually runs.
    for name in candidates("python3", "python", "py"):
        if locate_executable(name) and !(@(name) -c "" < @(os.devnull)):
            hand_off(name, *launcher_flags(name))
else:
    for name in candidates("python3", "python"):
        if locate_executable(name):
            hand_off(name)

print("te: no python3 on PATH (set TE_PYTHON)", file=sys.stderr)
sys.exit(1)
