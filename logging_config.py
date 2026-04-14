"""Project logging helpers."""

from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

_RESET_DONE: set[str] = set()


def _default_log_file() -> Path:
    raw_stem = Path(sys.argv[0] or "").stem.strip()
    safe_stem = re.sub(r"[^0-9A-Za-z._-]+", "_", raw_stem).strip("._-")
    if not safe_stem:
        safe_stem = "app"
    return Path("log") / f"{safe_stem}.log"


def setup_logger(
    log_level: int = logging.DEBUG,
    log_file: Optional[str] = None,
    reset_log: bool = False,
):
    """Configure the root logger for the current process."""
    resolved_log_file = Path(log_file) if log_file else _default_log_file()
    resolved_log_file.parent.mkdir(parents=True, exist_ok=True)
    resolved_log_file_key = str(resolved_log_file.resolve())

    log_format = (
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    if root_logger.handlers:
        for handler in root_logger.handlers:
            handler.close()
        root_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))

    if reset_log and resolved_log_file_key not in _RESET_DONE:
        resolved_log_file.write_text("", encoding="utf-8")
        _RESET_DONE.add(resolved_log_file_key)

    file_handler = RotatingFileHandler(
        resolved_log_file,
        mode="a",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(log_format))

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    root_logger.debug("日志系统已初始化，日志文件: %s", resolved_log_file.resolve())
    return root_logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a named logger that propagates to the configured root logger."""
    return logging.getLogger(name or "cudavox")
