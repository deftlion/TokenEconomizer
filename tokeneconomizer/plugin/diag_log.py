"""Level-filtered stderr diagnostic logger for plugin components."""
import logging
import sys


class _StderrHandler(logging.StreamHandler):
    def emit(self, record):
        self.stream = sys.stderr
        super().emit(record)


def make_stderr_logger(name, prefix, level_key):
    """Return a standalone logger that formats to current sys.stderr and filters by `level_key`."""
    def _configured_level(record):
        level = getattr(record, level_key, "warning").upper()
        return record.levelno >= getattr(logging, level, logging.WARNING)

    log = logging.Logger(name, logging.DEBUG)
    handler = _StderrHandler()
    handler.setFormatter(logging.Formatter(f"{prefix} %(levelname)s: %(message)s"))
    handler.addFilter(_configured_level)
    log.addHandler(handler)
    return log
