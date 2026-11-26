"""Broker connection: paper endpoint only, read-only, clear errors, no secrets.

Most tests use a fake Alpaca client (no network). The real alpaca-py
TradingClient is also built (it makes no network call until used) to prove
paper=True really selects the paper URL and that orders are blocked on it.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
import requests
from alpaca.common.enums import BaseURL
from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AccountStatus

from options_bot.broker import PaperBrokerClient
from options_bot.broker.alpaca_client import BLOCKED_METHODS, MARKET_TZ, mask_account_number
from options_bot.config import PAPER_TRADING_URL, load_settings
from options_bot.errors import (
    BrokerConnectionError, BrokerError, LiveTradingRefusedError, OrderSubmissionDisabledError,
)
from tests.conftest import FAKE_KEY, FAKE_SECRET


def fake_clock(**overrides):
    # Wednesday 2026-11-25, 15:00 UTC = 10:00 New York, market open.
    data = dict(timestamp=datetime(2026, 11, 25, 15, 0, tzinfo=timezone.utc), is_open=True,
                next_open=datetime(2026, 11, 27, 14, 30, tzinfo=timezone.utc),
                next_close=datetime(2026, 11, 25, 21, 0, tzinfo=timezone.utc))
    data.update(overrides)
    return SimpleNamespace(**data)


def fake_account(**overrides):
    data = dict(account_number="PA3ABCDE1234", status=AccountStatus.ACTIVE, currency="USD", cash="1000",
                equity="1000", buying_power="2000", options_buying_power="1000", options_trading_level=2,
                trading_blocked=False, account_blocked=False)
    data.update(overrides)
    return SimpleNamespace(**data)


class FakeTradingClient:
    """Stands in for alpaca-py's TradingClient. Records what was asked."""

    instances: list["FakeTradingClient"] = []

    def __init__(self, api_key, secret_key, paper, base_url=BaseURL.TRADING_PAPER, account=None, error=None,
                 clock=None, clock_error=None):
        self.kwargs = dict(api_key=api_key, secret_key=secret_key, paper=paper)
        self._base_url = base_url
        self._account = account or fake_account()
        self._error = error
        self._clock = clock or fake_clock()
        self._clock_error = clock_error
        self.submitted = []
        FakeTradingClient.instances.append(self)

    def get_account(self):
        if self._error:
            raise self._error
        return self._account

    def get_clock(self):
        if self._clock_error:
            raise self._clock_error
        return self._clock

    def submit_order(self, *args, **kwargs):  # would be a real order; must never run
        self.submitted.append((args, kwargs))

    def post(self, *args, **kwargs):
        self.submitted.append((args, kwargs))


def factory(**extra):
    return lambda **kw: FakeTradingClient(**kw, **extra)


def http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


# ------------------------------------------------------------- connectivity
def test_client_is_created_in_paper_mode(settings):
    PaperBrokerClient(settings, client_factory=factory())
    kwargs = FakeTradingClient.instances[-1].kwargs
    assert kwargs["paper"] is True
    assert kwargs["api_key"] == FAKE_KEY  # the real value only reaches alpaca-py


def test_account_summary(settings):
    summary = PaperBrokerClient(settings, client_factory=factory()).get_account_summary()
    assert summary.status == "ACTIVE" and summary.is_active
    assert summary.buying_power == Decimal("2000")
    assert summary.cash == Decimal("1000") and summary.equity == Decimal("1000")
    assert summary.options_buying_power == Decimal("1000")
    assert summary.options_trading_level == 2
    assert summary.account_number_masked == "********1234"
    assert summary.is_paper and summary.endpoint == PAPER_TRADING_URL


def test_blocked_account_is_not_active(settings):
    client = PaperBrokerClient(settings, client_factory=factory(account=fake_account(trading_blocked=True)))
    assert client.get_account_summary().is_active is False


def test_missing_optional_fields(settings):
    acct = fake_account(options_buying_power=None, options_trading_level=None, cash="")
    summary = PaperBrokerClient(settings, client_factory=factory(account=acct)).get_account_summary()
    assert summary.options_buying_power is None and summary.cash is None


def test_real_alpaca_client_targets_paper_url(settings):
    client = PaperBrokerClient(settings)  # real TradingClient, no request made yet
    assert str(client._client._base_url.value) == PAPER_TRADING_URL == BaseURL.TRADING_PAPER.value


def test_client_pointed_elsewhere_fails_closed(settings):
    with pytest.raises(LiveTradingRefusedError):
        PaperBrokerClient(settings, client_factory=factory(base_url=BaseURL.TRADING_LIVE))
    with pytest.raises(LiveTradingRefusedError):
        PaperBrokerClient(settings, client_factory=factory(base_url="https://example.com"))


def test_endpoint_property_is_paper(settings):
    assert PaperBrokerClient(settings, client_factory=factory()).endpoint == PAPER_TRADING_URL


def test_endpoint_property_rechecks_the_client(settings):
    client = PaperBrokerClient(settings, client_factory=factory())
    client._client._base_url = BaseURL.TRADING_LIVE  # simulate tampering after creation
    with pytest.raises(LiveTradingRefusedError):
        client.endpoint


# ------------------------------------------------------------- market clock
def test_market_clock_open_in_new_york_time(settings):
    clock = PaperBrokerClient(settings, client_factory=factory()).get_market_clock()
    assert clock.is_open is True
    assert clock.timestamp.tzinfo == MARKET_TZ and clock.timestamp.hour == 10
    assert clock.next_close.hour == 16
    assert clock.describe().startswith("OPEN (closes Wed 2026-11-25 16:00 EST")


def test_market_clock_closed(settings):
    client = PaperBrokerClient(settings, client_factory=factory(clock=fake_clock(is_open=False)))
    text = client.get_market_clock().describe()
    assert text.startswith("CLOSED (next open Fri 2026-11-27 09:30 EST")


def test_market_clock_naive_time_treated_as_utc(settings):
    clock = fake_clock(timestamp=datetime(2026, 7, 1, 14, 0))  # summer: UTC-4
    result = PaperBrokerClient(settings, client_factory=factory(clock=clock)).get_market_clock()
    assert result.timestamp.hour == 10


@pytest.mark.parametrize("overrides", [dict(is_open=None), dict(next_open="tomorrow"), dict(timestamp=None)])
def test_market_clock_bad_response(settings, overrides):
    client = PaperBrokerClient(settings, client_factory=factory(clock=fake_clock(**overrides)))
    with pytest.raises(BrokerError):
        client.get_market_clock()


def test_market_clock_network_failure(settings):
    client = PaperBrokerClient(settings, client_factory=factory(clock_error=requests.exceptions.ConnectionError()))
    with pytest.raises(BrokerConnectionError):
        client.get_market_clock()


def test_real_client_clock_uses_get_on_clock_path(settings, monkeypatch):
    """Prove alpaca-py's get_clock is a plain GET /v2/clock on the paper host."""
    seen = []

    def fake_request(self, method, url, **kwargs):
        seen.append((method, url))
        response = requests.Response()
        response.status_code = 200
        response._content = (b'{"timestamp": "2026-11-25T10:00:00-05:00", "is_open": true,'
                             b' "next_open": "2026-11-27T09:30:00-05:00", "next_close": "2026-11-25T16:00:00-05:00"}')
        return response

    monkeypatch.setattr(requests.Session, "request", fake_request)
    clock = PaperBrokerClient(settings).get_market_clock()
    assert seen == [("GET", "https://paper-api.alpaca.markets/v2/clock")]
    assert clock.is_open and clock.next_close.hour == 16


def test_unexpected_errors_become_broker_errors(settings):
    client = PaperBrokerClient(settings, client_factory=factory(error=ValueError(f"weird {FAKE_SECRET}")))
    with pytest.raises(BrokerError) as info:
        client.get_account_summary()
    assert "ValueError" in str(info.value) and FAKE_SECRET not in str(info.value)


# --------------------------------------------------------- orders are blocked
def test_wrapper_has_no_order_methods(settings):
    client = PaperBrokerClient(settings, client_factory=factory())
    public = {m for m in dir(client) if not m.startswith("_")}
    assert public == {"get_account_summary", "get_market_clock", "endpoint"}


def test_inner_fake_client_order_paths_blocked(settings):
    client = PaperBrokerClient(settings, client_factory=factory())
    inner = client._client
    for name in ("submit_order", "post"):
        with pytest.raises(OrderSubmissionDisabledError):
            getattr(inner, name)(symbol="SPY")
    assert inner.submitted == []


@pytest.mark.parametrize("name", BLOCKED_METHODS)
def test_every_write_method_blocked_on_real_alpaca_client(settings, name, monkeypatch):
    # If the block failed, the call would hit the network: make that loud.
    def no_network(*_a, **_k):
        raise AssertionError("network call attempted")
    monkeypatch.setattr(requests.Session, "request", no_network)
    client = PaperBrokerClient(settings)
    assert hasattr(TradingClient, name), f"alpaca-py no longer has {name}"
    with pytest.raises(OrderSubmissionDisabledError):
        getattr(client._client, name)("anything")


def test_all_alpaca_write_methods_are_listed():
    """If alpaca-py adds a new write method, this test reminds us to block it."""
    reads = {"get", "response_wrapper"} | {m for m in dir(TradingClient) if m.startswith("get_")}
    writes = {m for m in dir(TradingClient) if not m.startswith("_")} - reads
    assert writes <= set(BLOCKED_METHODS), f"unblocked write methods: {writes - set(BLOCKED_METHODS)}"


def test_submit_order_never_reaches_network_from_real_client_internals(settings, monkeypatch):
    calls = []
    monkeypatch.setattr(requests.Session, "request", lambda *a, **k: calls.append(a))
    client = PaperBrokerClient(settings)
    with pytest.raises(OrderSubmissionDisabledError):
        TradingClient.submit_order(client._client, order_data=SimpleNamespace(to_request_fields=lambda: {}))
    assert calls == []


# ------------------------------------------------------------------- errors
@pytest.mark.parametrize("status", [401, 403])
def test_bad_credentials_give_clear_error(settings, status, caplog):
    err = APIError('{"code": 40110000, "message": "request is not authorized"}', http_error(status))
    client = PaperBrokerClient(settings, client_factory=factory(error=err))
    with pytest.raises(BrokerError, match="PAPER keys"):
        client.get_account_summary()


def test_other_api_errors_and_non_json_bodies(settings):
    client = PaperBrokerClient(settings, client_factory=factory(error=APIError("<html>bad gateway</html>", http_error(502))))
    with pytest.raises(BrokerError, match="HTTP 502"):
        client.get_account_summary()


@pytest.mark.parametrize("exc", [requests.exceptions.ConnectionError("dns"), requests.exceptions.Timeout("slow")])
def test_network_failures(settings, exc):
    client = PaperBrokerClient(settings, client_factory=factory(error=exc))
    with pytest.raises(BrokerConnectionError):
        client.get_account_summary()


def test_errors_and_repr_never_contain_secrets(settings, caplog):
    caplog.set_level(logging.DEBUG)
    err = APIError(f'{{"message": "bad key {FAKE_KEY}"}}', http_error(401))
    client = PaperBrokerClient(settings, client_factory=factory(error=err))
    with pytest.raises(BrokerError) as info:
        client.get_account_summary()
    assert info.value.__cause__ is None and info.value.__suppress_context__
    for text in (str(info.value), repr(client)):
        assert FAKE_KEY not in text and FAKE_SECRET not in text


def test_mask_account_number():
    assert mask_account_number("PA3ABCDE1234") == "********1234"
    assert mask_account_number(None) == "unknown"
    assert mask_account_number("12") == "12"


# ------------------------------------------------------- optional live test
@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("ALPACA_API_KEY"), reason="set ALPACA_API_KEY/ALPACA_SECRET_KEY (paper) to run")
def test_real_paper_account_connection():
    settings = load_settings(dict(os.environ))
    client = PaperBrokerClient(settings)
    summary = client.get_account_summary()
    assert summary.status != "unknown"
    assert summary.is_paper
    assert isinstance(client.get_market_clock().is_open, bool)
