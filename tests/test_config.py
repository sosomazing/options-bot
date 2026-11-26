"""Configuration must accept paper settings and refuse everything else."""

from __future__ import annotations

import pickle
from decimal import Decimal

import pytest

from options_bot import config
from options_bot.config import PAPER_TRADING_URL, Secret, load_settings
from options_bot.errors import ConfigError, LiveTradingRefusedError
from tests.conftest import FAKE_KEY, FAKE_SECRET


def test_valid_paper_settings_load(valid_env):
    s = load_settings(valid_env)
    assert s.is_paper
    assert s.base_url == PAPER_TRADING_URL
    assert s.trading_mode == "paper"
    assert s.starting_balance == Decimal("1000")
    assert s.order_submission_enabled is False


def test_defaults_are_paper_and_1000(valid_env):
    for name in ("ALPACA_BASE_URL", "TRADING_MODE", "STARTING_BALANCE", "DATABASE_URL", "LOG_LEVEL"):
        valid_env.pop(name)
    s = load_settings(valid_env)
    assert s.base_url == PAPER_TRADING_URL
    assert s.starting_balance == Decimal("1000")


def test_order_submission_is_a_hard_constant():
    assert config.ORDER_SUBMISSION_ENABLED is False


@pytest.mark.parametrize("url", ["https://paper-api.alpaca.markets/", "https://paper-api.alpaca.markets/v2",
                                 "  https://PAPER-API.alpaca.markets  "])
def test_paper_url_variants_are_normalised(valid_env, url):
    valid_env["ALPACA_BASE_URL"] = url
    assert load_settings(valid_env).base_url == PAPER_TRADING_URL


@pytest.mark.parametrize(
    "url",
    [
        "https://api.alpaca.markets",
        "https://api.alpaca.markets/v2",
        "http://paper-api.alpaca.markets",               # not https
        "https://paper-api.alpaca.markets.evil.com",     # look-alike host
        "https://paper-api.alpaca.markets:8443",
        "https://user:pw@paper-api.alpaca.markets",
        "https://paper-api.alpaca.markets/v2/orders",
        "https://data.alpaca.markets",
        "not a url",
    ],
)
def test_non_paper_urls_fail_closed(valid_env, url):
    valid_env["ALPACA_BASE_URL"] = url
    with pytest.raises(LiveTradingRefusedError):
        load_settings(valid_env)


def test_legacy_apca_live_url_is_refused(valid_env):
    valid_env["APCA_API_BASE_URL"] = "https://api.alpaca.markets"
    with pytest.raises(LiveTradingRefusedError):
        load_settings(valid_env)


@pytest.mark.parametrize("mode", ["live", "LIVE", "real", "production"])
def test_live_mode_is_refused(valid_env, mode):
    valid_env["TRADING_MODE"] = mode
    with pytest.raises(LiveTradingRefusedError):
        load_settings(valid_env)


def test_live_mode_refused_even_without_keys():
    with pytest.raises(LiveTradingRefusedError):
        load_settings({"TRADING_MODE": "live"})


def test_live_key_prefix_is_refused(valid_env):
    valid_env["ALPACA_API_KEY"] = "AKLIVEKEY000000000001"
    with pytest.raises(LiveTradingRefusedError) as info:
        load_settings(valid_env)
    assert "AKLIVEKEY000000000001" not in str(info.value)


def test_unknown_key_prefix_is_refused(valid_env):
    valid_env["ALPACA_API_KEY"] = "XX12345678901234567"
    with pytest.raises(LiveTradingRefusedError):
        load_settings(valid_env)


@pytest.mark.parametrize("name", ["ALPACA_API_KEY", "ALPACA_SECRET_KEY"])
def test_missing_keys_fail(valid_env, name):
    valid_env.pop(name)
    with pytest.raises(ConfigError):
        load_settings(valid_env)


def test_example_placeholders_are_rejected(valid_env):
    valid_env["ALPACA_API_KEY"] = "PK_your_paper_key_id_here"
    with pytest.raises(ConfigError):
        load_settings(valid_env)


@pytest.mark.parametrize("value", ["abc", "0", "-5", "NaN", "Infinity"])
def test_bad_starting_balance(valid_env, value):
    valid_env["STARTING_BALANCE"] = value
    with pytest.raises(ConfigError):
        load_settings(valid_env)


def test_only_sqlite_database(valid_env):
    valid_env["DATABASE_URL"] = "postgresql://localhost/db"
    with pytest.raises(ConfigError):
        load_settings(valid_env)


def test_bad_log_level(valid_env):
    valid_env["LOG_LEVEL"] = "LOUD"
    with pytest.raises(ConfigError):
        load_settings(valid_env)


def test_settings_never_show_secrets(settings):
    for text in (repr(settings), str(settings), f"{settings}", repr(settings.api_key),
                 str(settings.secret_key), f"{settings.secret_key}"):
        assert FAKE_KEY not in text
        assert FAKE_SECRET not in text
    assert settings.api_key.reveal() == FAKE_KEY


def test_secret_cannot_be_pickled():
    with pytest.raises(TypeError):
        pickle.dumps(Secret("abc"))


def test_settings_are_read_only(settings):
    with pytest.raises(AttributeError):
        settings.base_url = "https://api.alpaca.markets"  # type: ignore[misc]


def test_loads_from_dotenv_file(tmp_path, monkeypatch):
    for name in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_BASE_URL", "TRADING_MODE", "APCA_API_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(f"ALPACA_API_KEY={FAKE_KEY}\nALPACA_SECRET_KEY={FAKE_SECRET}\n", encoding="utf-8")
    s = load_settings(dotenv_path=env_file)
    assert s.is_paper and s.api_key.reveal() == FAKE_KEY


def test_environment_variable_beats_dotenv_and_is_still_checked(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(f"ALPACA_API_KEY={FAKE_KEY}\nALPACA_SECRET_KEY={FAKE_SECRET}\n", encoding="utf-8")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://api.alpaca.markets")
    with pytest.raises(LiveTradingRefusedError):
        load_settings(dotenv_path=env_file)
