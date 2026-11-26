"""Logging must never write credentials, even by accident."""

from __future__ import annotations

import logging

import pytest

from options_bot.logging_setup import REDACTED, RedactingFilter, setup_logging
from tests.conftest import FAKE_KEY, FAKE_SECRET


@pytest.fixture
def log_file(tmp_path):
    path = tmp_path / "bot.log"
    setup_logging("DEBUG", secrets=[FAKE_KEY, FAKE_SECRET], log_file=path)
    yield path
    setup_logging("WARNING", log_file=None)


def _flush():
    for handler in logging.getLogger().handlers:
        handler.flush()


def test_known_secrets_are_redacted_in_file_and_console(log_file, capsys):
    log = logging.getLogger("options_bot.test")
    log.info("key=%s secret=%s", FAKE_KEY, FAKE_SECRET)
    log.warning(f"inline {FAKE_SECRET} value")
    _flush()
    content = log_file.read_text(encoding="utf-8") + capsys.readouterr().err
    assert FAKE_KEY not in content and FAKE_SECRET not in content
    assert REDACTED in content


def test_exception_tracebacks_are_redacted(log_file):
    try:
        raise ValueError(f"failed with {FAKE_SECRET}")
    except ValueError:
        logging.getLogger("options_bot.test").exception("oops")
    _flush()
    content = log_file.read_text(encoding="utf-8")
    assert "ValueError" in content and FAKE_SECRET not in content


@pytest.mark.parametrize("text", [
    "PKABCDEFGHIJKLMNOP12 leaked",
    "AKABCDEFGHIJKLMNOP12 leaked",
    "APCA-API-SECRET-KEY: s3cr3tValue",
    "headers={'APCA-API-KEY-ID': 'PKZZZZZZZZZZZZZZZZZZ'}",
    "secret_key=abc123def456",
])
def test_unknown_key_shapes_are_redacted(text):
    out = RedactingFilter().redact(text)
    assert REDACTED in out
    for fragment in ("PKABCDEFGHIJKLMNOP12", "AKABCDEFGHIJKLMNOP12", "s3cr3tValue", "PKZZZZZZZZZZZZZZZZZZ", "abc123def456"):
        assert fragment not in out


def test_ordinary_messages_untouched():
    assert RedactingFilter().redact("Connected to SPY at 500.12") == "Connected to SPY at 500.12"


def test_setup_creates_log_folder(tmp_path):
    path = tmp_path / "nested" / "logs" / "bot.log"
    setup_logging("INFO", log_file=path)
    logging.getLogger("options_bot").info("hello")
    _flush()
    assert path.exists()
    setup_logging("WARNING", log_file=None)
