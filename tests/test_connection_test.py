"""The connection test command: right steps, right messages, no secrets."""

from __future__ import annotations

from options_bot import connection_test
from options_bot.broker import PaperBrokerClient
from options_bot.config import load_settings
from options_bot.connection_test import format_report, run_connection_test
from options_bot.errors import ConfigError
from tests.conftest import FAKE_KEY, FAKE_SECRET
from tests.test_broker import factory, fake_clock, http_error

import pytest
import requests
from alpaca.common.enums import BaseURL
from alpaca.common.exceptions import APIError


@pytest.fixture(autouse=True)
def no_log_file(monkeypatch):
    # Keep test runs out of the real logs/ folder.
    real = connection_test.setup_logging
    monkeypatch.setattr(connection_test, "setup_logging", lambda level, secrets: real(level, secrets, log_file=None))


def _run(valid_env, **client_kwargs):
    return run_connection_test(
        settings_loader=lambda: load_settings(valid_env),
        client_factory=lambda s: PaperBrokerClient(s, client_factory=factory(**client_kwargs)),
    )


def _no_secrets(text):
    assert FAKE_KEY not in text and FAKE_SECRET not in text


def test_success(valid_env):
    report = _run(valid_env)
    text = format_report(report)
    assert report.ok and report.exit_code == 0
    assert [passed for _, passed, _ in report.steps] == [True, True, True, True]
    assert "CONNECTION SUCCESS" in text
    for expected in ("Equity:        $1,000.00", "Buying power:  $2,000.00", "Cash:          $1,000.00",
                     "Status:        ACTIVE", "Market:        OPEN", "paper-api.alpaca.markets"):
        assert expected in text
    _no_secrets(text)


def test_market_closed_is_still_success(valid_env):
    report = _run(valid_env, clock=fake_clock(is_open=False))
    assert report.ok and "Market:        CLOSED" in format_report(report)


def test_missing_settings(valid_env):
    def loader():
        raise ConfigError("ALPACA_API_KEY is missing.")
    report = run_connection_test(settings_loader=loader)
    assert not report.ok and report.exit_code == 2
    assert "CONNECTION FAILED: ALPACA_API_KEY is missing." in format_report(report)


def test_live_url_refused_before_connecting(valid_env):
    valid_env["ALPACA_BASE_URL"] = "https://api.alpaca.markets"
    called = []
    report = run_connection_test(settings_loader=lambda: load_settings(valid_env),
                                 client_factory=lambda s: called.append(s))
    assert not report.ok and report.exit_code == 2 and called == []
    assert "LIVE endpoint" in format_report(report)


def test_client_on_wrong_endpoint_fails(valid_env):
    report = _run(valid_env, base_url=BaseURL.TRADING_LIVE)
    assert not report.ok and report.exit_code == 2
    assert report.steps[-1][0] == "Paper endpoint check" and report.steps[-1][1] is False


def test_bad_credentials(valid_env):
    report = _run(valid_env, error=APIError('{"message": "unauthorized"}', http_error(401)))
    text = format_report(report)
    assert not report.ok and report.exit_code == 3
    assert "CONNECTION FAILED" in text and "PAPER keys" in text
    _no_secrets(text)


def test_clock_failure_reported_after_account(valid_env):
    report = _run(valid_env, clock_error=requests.exceptions.Timeout())
    assert not report.ok and report.exit_code == 3
    assert report.account is not None
    assert report.steps[-1][0].startswith("Market clock") and report.steps[-1][1] is False


def test_no_orders_attempted(valid_env):
    report = _run(valid_env)
    assert report.ok
    from tests.test_broker import FakeTradingClient
    assert FakeTradingClient.instances[-1].submitted == []


def test_main_prints_banner_and_result(valid_env, monkeypatch, capsys):
    monkeypatch.setattr(connection_test, "run_connection_test", lambda: _run(valid_env))
    assert connection_test.main() == 0
    out = capsys.readouterr().out
    assert "PAPER TRADING ONLY" in out and "CONNECTION SUCCESS" in out
    _no_secrets(out)
