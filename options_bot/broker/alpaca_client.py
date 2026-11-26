"""A read-only, paper-only connection to Alpaca.

What this file does, in plain terms:
* It creates alpaca-py's ``TradingClient`` with ``paper=True``, which points
  it at https://paper-api.alpaca.markets (see alpaca-py ``BaseURL.TRADING_PAPER``).
* It double-checks the URL the client actually ended up with, and stops if it
  isn't the paper URL.
* It **disables every method that could change anything**: placing, changing
  or cancelling orders, closing positions, exercising options, and the raw
  POST/PUT/PATCH/DELETE calls those methods use. Calling any of them raises
  ``OrderSubmissionDisabledError``. Only reading is possible.
* It turns Alpaca's errors into our own clear error types, without ever
  putting your keys in the message.

Alpaca docs used:
* Docs home:      https://docs.alpaca.markets/  (Paper Trading section)
* Get account:    https://docs.alpaca.markets/reference/getaccount  (GET /v2/account)
* alpaca-py:      https://github.com/alpacahq/alpaca-py
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

import requests
from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient

from options_bot.config import ORDER_SUBMISSION_ENABLED, PAPER_TRADING_URL, Settings
from options_bot.errors import (
    BrokerConnectionError,
    BrokerError,
    LiveTradingRefusedError,
    OrderSubmissionDisabledError,
)

log = logging.getLogger(__name__)

# Every TradingClient method that writes something. Each is replaced with a
# function that raises. The raw HTTP verbs are what the others call inside,
# so blocking them closes any path we didn't list by name.
BLOCKED_METHODS: tuple[str, ...] = (
    "submit_order",
    "replace_order_by_id",
    "cancel_order_by_id",
    "cancel_orders",
    "close_position",
    "close_all_positions",
    "exercise_options_position",
    "set_account_configurations",
    "create_watchlist",
    "update_watchlist_by_id",
    "delete_watchlist_by_id",
    "add_asset_to_watchlist_by_id",
    "remove_asset_from_watchlist_by_id",
    "post",
    "put",
    "patch",
    "delete",
)


def _blocked(name: str) -> Callable[..., Any]:
    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        log.error("Blocked a call to TradingClient.%s: order submission is disabled in stage 1.", name)
        raise OrderSubmissionDisabledError(
            f"TradingClient.{name}() is disabled. This development stage never places, changes or cancels orders."
        )

    refuse.__name__ = f"blocked_{name}"
    return refuse


def mask_account_number(value: str | None) -> str:
    """'PA3ABC12345' -> '*******2345'. Enough to recognise, not to misuse."""
    if not value:
        return "unknown"
    return "*" * max(len(value) - 4, 0) + value[-4:]


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _api_error_text(exc: APIError) -> str:
    """Alpaca's error message. Its .message property crashes on non-JSON bodies."""
    try:
        return str(exc.message)
    except (ValueError, KeyError, TypeError):
        return str(exc)[:200]


def _enum_text(value: Any) -> str:
    return str(getattr(value, "value", value) or "unknown")


@dataclass(frozen=True)
class AccountSummary:
    """The account facts the dashboard shows. Money values are ``Decimal``."""

    account_number_masked: str
    status: str
    currency: str
    cash: Decimal | None
    equity: Decimal | None
    buying_power: Decimal | None
    options_buying_power: Decimal | None
    options_trading_level: int | None
    trading_blocked: bool
    account_blocked: bool
    endpoint: str = PAPER_TRADING_URL
    is_paper: bool = True

    @property
    def is_active(self) -> bool:
        return self.status == "ACTIVE" and not self.trading_blocked and not self.account_blocked


class PaperBrokerClient:
    """Read-only Alpaca paper client. It has no way to submit orders."""

    def __init__(
        self,
        settings: Settings,
        client_factory: Callable[..., TradingClient] = TradingClient,
    ) -> None:
        if not settings.is_paper:
            raise LiveTradingRefusedError("PaperBrokerClient only accepts paper settings.")
        if ORDER_SUBMISSION_ENABLED:  # constant; guards against a careless edit
            raise LiveTradingRefusedError("ORDER_SUBMISSION_ENABLED must stay False in stage 1.")

        # paper=True selects the paper URL inside alpaca-py. No url_override,
        # so nothing in settings can redirect the client somewhere else.
        client = client_factory(
            api_key=settings.api_key.reveal(),
            secret_key=settings.secret_key.reveal(),
            paper=True,
        )
        self._verify_endpoint(client)
        for name in BLOCKED_METHODS:
            setattr(client, name, _blocked(name))
        self._client = client
        log.info("Alpaca client ready (PAPER, read-only) -> %s", PAPER_TRADING_URL)

    @staticmethod
    def _verify_endpoint(client: Any) -> None:
        actual = str(getattr(getattr(client, "_base_url", None), "value", getattr(client, "_base_url", "")))
        if actual.rstrip("/") != PAPER_TRADING_URL:
            raise LiveTradingRefusedError(
                f"Alpaca client is pointed at {actual!r}, not the paper endpoint. Refusing to continue."
            )

    def __repr__(self) -> str:  # never show the inner client (it holds the keys)
        return f"PaperBrokerClient(endpoint={PAPER_TRADING_URL!r}, read_only=True)"

    # ------------------------------------------------------------------ reads
    def get_account_summary(self) -> AccountSummary:
        """GET /v2/account -> status, cash, equity and buying power."""
        account = self._call("get_account")
        return AccountSummary(
            account_number_masked=mask_account_number(getattr(account, "account_number", None)),
            status=_enum_text(getattr(account, "status", None)),
            currency=str(getattr(account, "currency", None) or "USD"),
            cash=_to_decimal(getattr(account, "cash", None)),
            equity=_to_decimal(getattr(account, "equity", None)),
            buying_power=_to_decimal(getattr(account, "buying_power", None)),
            options_buying_power=_to_decimal(getattr(account, "options_buying_power", None)),
            options_trading_level=getattr(account, "options_trading_level", None),
            trading_blocked=bool(getattr(account, "trading_blocked", False)),
            account_blocked=bool(getattr(account, "account_blocked", False)),
        )

    # --------------------------------------------------------------- helpers
    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Run one read call and translate failures into our error types."""
        try:
            return getattr(self._client, method)(*args, **kwargs)
        except OrderSubmissionDisabledError:
            raise
        except APIError as exc:
            status = getattr(exc, "status_code", None)
            if status in (401, 403):
                msg = (
                    "Alpaca rejected the credentials (HTTP %s). Make sure they are PAPER keys "
                    "from the Paper dashboard and that they were copied completely." % status
                )
            else:
                msg = f"Alpaca returned an error for {method} (HTTP {status}): {_api_error_text(exc)}"
            log.error(msg)
            raise BrokerError(msg) from None  # 'from None' keeps request details out of tracebacks
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            msg = f"Could not reach Alpaca paper API ({type(exc).__name__}). Check your internet connection."
            log.error(msg)
            raise BrokerConnectionError(msg) from None
        except requests.exceptions.RequestException as exc:
            msg = f"Network error talking to Alpaca ({type(exc).__name__})."
            log.error(msg)
            raise BrokerConnectionError(msg) from None
