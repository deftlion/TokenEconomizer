"""Side-call diagnostics are level-filtered and omit call content."""
import subprocess

import pytest

from tokeneconomizer.plugin import sidecall
from tokeneconomizer.plugin.config import LiveConfig


@pytest.mark.parametrize("level,visible", [("debug", True), ("info", True),
                                           ("warning", False), ("critical", False)])
def test_host_logging_respects_level_and_does_not_leak(monkeypatch, capsys, level, visible):
    monkeypatch.setattr(sidecall, "pi_call", lambda prompt, **kw: ("secret reply", 4))
    runner = sidecall.runner_for("pi", LiveConfig(log_level=level), role="judge")
    assert runner("secret prompt") == ("secret reply", 4)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert ("host call started" in captured.err) is visible
    assert ("host call finished" in captured.err) is visible
    assert "secret" not in captured.err


def test_timeout_logs_without_command(monkeypatch, capsys):
    monkeypatch.setattr(sidecall, "_log", lambda text: None)
    def fail(prompt, model):
        raise subprocess.TimeoutExpired(["secret prompt"], 1)
    runner = sidecall._noted("pi", fail, LiveConfig(), "judge")
    with pytest.raises(subprocess.TimeoutExpired):
        runner("secret prompt")
    err = capsys.readouterr().err
    assert "timed out" in err
    assert "secret" not in err


def test_local_fallback_logging(monkeypatch, capsys):
    monkeypatch.setattr(sidecall, "local_routes", lambda role, config: True)
    monkeypatch.setattr(sidecall, "fm_available", lambda: True)
    monkeypatch.setattr(sidecall, "fm_call", lambda prompt, schema: (None, 0))
    runner = sidecall.local_runner("judge", LiveConfig(log_level="info"),
                                   fallback=lambda prompt, model: ("reply", 1))
    assert runner("private") == ("reply", 1)
    assert runner.answered_locally is False
    err = capsys.readouterr().err
    assert "local call started" in err and "fallback=True" in err
    assert "private" not in err
