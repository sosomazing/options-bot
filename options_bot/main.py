"""Command-line health check: ``python -m options_bot``.

It loads settings, sets up logging and the database, connects to the Alpaca
PAPER API, prints your account status and buying power, and exits.
It never places an order.

Exit codes: 0 = all good, 2 = settings problem, 3 = Alpaca problem, 4 = database problem.
"""

from __future__ import annotations

import logging
import sys

from sqlalchemy.exc import SQLAlchemyError

from options_bot.broker import AccountSummary, PaperBrokerClient
from options_bot.config import load_settings
from options_bot.db import init_db, make_engine
from options_bot.errors import BrokerError, ConfigError
from options_bot.logging_setup import setup_logging

BANNER = "\n".join(
    [
        "=" * 64,
        "  PAPER TRADING ONLY  |  simulated money  |  orders DISABLED",
        "  Endpoint: https://paper-api.alpaca.markets",
        "=" * 64,
    ]
)


def _money(value) -> str:
    return "n/a" if value is None else f"${value:,.2f}"


def format_summary(summary: AccountSummary, starting_balance) -> str:
    lines = [
        f"Account:              {summary.account_number_masked}",
        f"Status:               {summary.status}{'' if summary.is_active else '  (NOT ready to trade)'}",
        f"Cash:                 {_money(summary.cash)}",
        f"Equity:               {_money(summary.equity)}",
        f"Buying power:         {_money(summary.buying_power)}",
        f"Options buying power: {_money(summary.options_buying_power)}",
        f"Options level:        {summary.options_trading_level if summary.options_trading_level is not None else 'n/a'}",
        f"Trading blocked:      {summary.trading_blocked}",
        f"Account blocked:      {summary.account_blocked}",
    ]
    if summary.equity is not None and summary.equity != starting_balance:
        lines.append(
            f"Note: equity differs from STARTING_BALANCE ({_money(starting_balance)}). "
            "Reset the paper account in the Alpaca dashboard if you want to start at that amount."
        )
    return "\n".join(lines)


def main() -> int:
    print(BANNER)
    try:
        settings = load_settings()
    except ConfigError as exc:
        # Logging isn't set up yet; the message never contains a key value.
        print(f"\nSETTINGS ERROR: {exc}", file=sys.stderr)
        return 2

    log = setup_logging(settings.log_level, secrets=settings.secrets())
    log.info("Starting stage 1 health check (paper mode, orders disabled)")

    try:
        init_db(make_engine(settings.database_url))
    except (SQLAlchemyError, OSError) as exc:
        log.error("Database problem: %s", exc)
        return 4

    try:
        summary = PaperBrokerClient(settings).get_account_summary()
    except BrokerError as exc:
        log.error("Alpaca problem: %s", exc)
        return 3

    print("\n" + format_summary(summary, settings.starting_balance) + "\n")
    log.info("Connected to Alpaca paper account %s (status %s)", summary.account_number_masked, summary.status)
    return 0


if __name__ == "__main__":
    logging.captureWarnings(True)
    sys.exit(main())
