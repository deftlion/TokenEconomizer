"""Fold diagnostics respect the per-repository setting without configuring root logging."""
import logging
from types import SimpleNamespace

import pytest

from tokeneconomizer.plugin import fold
from tokeneconomizer.plugin.config import LiveConfig


@pytest.mark.parametrize("threshold,expected", [
    ("debug", ["DEBUG", "INFO", "WARNING"]),
    ("info", ["INFO", "WARNING"]),
    ("warning", ["WARNING"]),
    ("error", []),
])
def test_fold_log_levels_and_stderr(threshold, expected, capsys):
    root_level = logging.getLogger().level
    for level in (logging.DEBUG, logging.INFO, logging.WARNING):
        fold.logger.log(level, "message", extra={"fold_log_level": threshold})
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines() == [f"fold {level}: message" for level in expected]
    assert logging.getLogger().level == root_level


def test_fold_session_reports_import_deferral_at_debug(monkeypatch, capsys):
    ctx = SimpleNamespace(config=LiveConfig(log_level="debug"))
    monkeypatch.setattr(fold, "import_blocks", lambda ctx: True)
    assert fold.fold_session(ctx, "session") is None
    assert "session deferred: history import in progress" in capsys.readouterr().err
