"""Connection test: ``python -m options_bot.connection_test``.

Checks, in order, and stops at the first failure:
  1. Settings load from .env and are PAPER-only (keys are never shown).
  2. The alpaca-py TradingClient is created with paper=True and really points
     at https://paper-api.alpaca.markets.
  3. GET /v2/account works: status, equity, buying power, cash.
  4. GET /v2/clock works: is the market open, next open/close.
Then prints CONNECTION SUCCESS or CONNECTION FAILED.

Read-only. It never submits, modifies or cancels an order.
Exit codes: 0 success, 2 settings problem, 3 Alpaca problem.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Callable

from options_bot.broker import AccountSummary, MarketClock, PaperBrokerClient
from options_bot.config import PAPER_TRADING_URL, Settings, load_settings
from options_bot.errors import BrokerError, ConfigError, LiveTradingRefusedError
from options_bot.logging_setup import setup_logging

BANNER = "\n".join(
    [
        "=" * 64,
        "  ALPACA CONNECTION TEST  |  PAPER TRADING ONLY  |  orders DISABLED",
        "=" * 64,
    ]
)


@dataclass
class ConnectionReport:
    """What happened at each step. Contains no credentials."""

    ok: bool = False
    exit_code: int = 1
    steps: list[tuple[str, bool, str]] = field(default_factory=list)
    account: AccountSummary | None = None
    clock: MarketClock | None = None
    error: str | None = None

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.steps.append((name, passed, detail))


def _money(value) -> str:
    return "n/a" if value is None else f"${value:,.2f}"


def run_connection_test(
    settings_loader: Callable[[], Settings] = load_settings,
    client_factory: Callable[[Settings], PaperBrokerClient] = PaperBrokerClient,
) -> ConnectionReport:
    report = ConnectionReport()

    try:
        settings = settings_loader()
    except ConfigError as exc:  # includes LiveTradingRefusedError
        report.add("Load settings (.env)", False, str(exc))
        report.error, report.exit_code = str(exc), 2
        return report
    report.add("Load settings (.env)", True, "paper mode, keys loaded (hidden)")
    setup_logging(settings.log_level, secrets=settings.secrets())

    try:
        client = client_factory(settings)
        endpoint = client.endpoint
    except LiveTradingRefusedError as exc:
        report.add("Paper endpoint check", False, str(exc))
        report.error, report.exit_code = str(exc), 2
        return report
    report.add("Paper endpoint check", endpoint == PAPER_TRADING_URL, endpoint)

    try:
        report.account = client.get_account_summary()
        report.add("Account (GET /v2/account)", True, f"status {report.account.status}")
        report.clock = client.get_market_clock()
        report.add("Market clock (GET /v2/clock)", True, report.clock.describe())
    except BrokerError as exc:
        step = "Account (GET /v2/account)" if report.account is None else "Market clock (GET /v2/clock)"
        report.add(step, False, str(exc))
        report.error, report.exit_code = str(exc), 3
        return report

    report.ok, report.exit_code = True, 0
    return report


def format_report(report: ConnectionReport) -> str:
    lines = [""]
    for name, passed, detail in report.steps:
        lines.append(f"  [{'PASS' if passed else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
    if report.account:
        a = report.account
        lines += [
            "",
            f"  Account:       {a.account_number_masked}",
            f"  Status:        {a.status}{'' if a.is_active else '  (NOT ready to trade)'}",
            f"  Equity:        {_money(a.equity)}",
            f"  Buying power:  {_money(a.buying_power)}",
            f"  Cash:          {_money(a.cash)}",
        ]
    if report.clock:
        lines.append(f"  Market:        {report.clock.describe()}")
    lines.append("")
    if report.ok:
        lines.append("CONNECTION SUCCESS: connected to the Alpaca PAPER trading API.")
    else:
        lines.append(f"CONNECTION FAILED: {report.error}")
    return "\n".join(lines)


def main() -> int:
    print(BANNER)
    report = run_connection_test()
    print(format_report(report), file=sys.stdout if report.ok else sys.stderr)
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
