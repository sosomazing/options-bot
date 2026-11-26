"""Logging: a diary of what the bot did, with secrets blanked out.

Every message goes to the screen and to ``logs/options_bot.log``. The log file
rotates at 1 MB and keeps 5 old copies, so it can't fill your disk.

``RedactingFilter`` runs on every message before it's written. It replaces
your exact key values, plus anything that *looks* like an Alpaca key, with
``[REDACTED]``. Even if a future bug logged a key, it would not reach the file.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Iterable

from options_bot.config import PROJECT_ROOT

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DEFAULT_LOG_FILE = PROJECT_ROOT / "logs" / "options_bot.log"
REDACTED = "[REDACTED]"

# Alpaca key IDs: PK/AK + 16 or more uppercase letters/digits. Also catches
# "secret=..." / "APCA-API-SECRET-KEY: ..." style pairs.
_KEY_PATTERNS = [
    re.compile(r"\b(?:PK|AK)[A-Z0-9]{14,}\b"),
    re.compile(
        r"(?i)((?:secret|api[_-]?key|apca-api-(?:key-id|secret-key)|password|token)\w*['\"]?\s*[:=]\s*['\"]?)"
        r"([^\s'\",}]+)"
    ),
]


class RedactingFilter(logging.Filter):
    """Removes credentials from log records."""

    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets = sorted({s for s in secrets if s and len(s) >= 4}, key=len, reverse=True)

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        text = _KEY_PATTERNS[0].sub(REDACTED, text)
        text = _KEY_PATTERNS[1].sub(lambda m: m.group(1) + REDACTED, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        # Build the final text first (so "%s" arguments are covered), then scrub.
        message = self.redact(record.getMessage())
        record.msg, record.args = message, None
        if record.exc_info:
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = self.redact(formatted)
            record.exc_info = None
        if record.stack_info:
            record.stack_info = self.redact(record.stack_info)
        return True


def setup_logging(
    level: str = "INFO",
    secrets: Iterable[str] = (),
    log_file: Path | None = DEFAULT_LOG_FILE,
) -> logging.Logger:
    """Configure the root logger once. Safe to call again (replaces handlers)."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    redactor = RedactingFilter(secrets)
    formatter = logging.Formatter(LOG_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(redactor)
    root.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.addFilter(redactor)
        root.addHandler(file_handler)

    root.setLevel(level)
    # Chatty network libraries stay quiet even in DEBUG.
    for noisy in ("urllib3", "requests", "websockets", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return logging.getLogger("options_bot")
