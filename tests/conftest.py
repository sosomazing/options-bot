"""Shared test fixtures. These keys are fake and only shaped like paper keys."""

from __future__ import annotations

import pytest

from options_bot.config import load_settings

FAKE_KEY = "PKTESTFAKEKEY0000000001"
FAKE_SECRET = "fakeSecretValueForTestsOnly0000000000001"


@pytest.fixture
def valid_env() -> dict[str, str]:
    return {
        "ALPACA_API_KEY": FAKE_KEY,
        "ALPACA_SECRET_KEY": FAKE_SECRET,
        "ALPACA_BASE_URL": "https://paper-api.alpaca.markets",
        "TRADING_MODE": "paper",
        "STARTING_BALANCE": "1000",
        "DATABASE_URL": "sqlite:///:memory:",
        "LOG_LEVEL": "INFO",
    }


@pytest.fixture
def settings(valid_env):
    return load_settings(valid_env)
