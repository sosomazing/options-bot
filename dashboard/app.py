"""Streamlit dashboard: ``streamlit run dashboard/app.py``.

Shows paper account status and the local database. Read-only: there are no
buttons that trade. Keys are never displayed; errors are shown as plain text
without any credential.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make "options_bot" importable when Streamlit runs this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from options_bot.broker import PaperBrokerClient  # noqa: E402
from options_bot.config import PAPER_TRADING_URL, load_settings  # noqa: E402
from options_bot.db import init_db, make_engine, make_session_factory, session_scope  # noqa: E402
from options_bot.db.repository import open_positions, recent_signals, recent_trades, table_counts  # noqa: E402
from options_bot.errors import BrokerError, ConfigError  # noqa: E402
from options_bot.logging_setup import setup_logging  # noqa: E402

st.set_page_config(page_title="Options Bot (PAPER)", layout="wide")

st.markdown(
    """
    <div style="background:#b45309;color:#fff;padding:18px 22px;border-radius:8px;
                font-size:1.35rem;font-weight:700;letter-spacing:.02em;text-align:center;">
      PAPER TRADING ONLY &middot; simulated money &middot; order submission DISABLED
    </div>
    """,
    unsafe_allow_html=True,
)
st.title("Options Bot")
st.caption(f"Stage 1 foundation. Connected endpoint: {PAPER_TRADING_URL}")


def money(value) -> str:
    return "n/a" if value is None else f"${value:,.2f}"


try:
    settings = load_settings()
except ConfigError as exc:
    st.error(f"Settings problem: {exc}")
    st.info("Copy .env.example to .env in the options-bot folder and add your Alpaca PAPER keys.")
    st.stop()


@st.cache_resource
def _resources(database_url: str, log_level: str):
    setup_logging(log_level, secrets=settings.secrets())
    engine = make_engine(database_url)
    init_db(engine)
    return make_session_factory(engine), PaperBrokerClient(settings)


try:
    sessions, broker = _resources(settings.database_url, settings.log_level)
except BrokerError as exc:
    st.error(f"Alpaca problem: {exc}")
    st.stop()

st.subheader("Paper account")
try:
    account = broker.get_account_summary()
except BrokerError as exc:
    st.error(f"Could not load the account: {exc}")
else:
    status_text = account.status if account.is_active else f"{account.status} (not ready to trade)"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", status_text)
    c2.metric("Equity", money(account.equity))
    c3.metric("Buying power", money(account.buying_power))
    c4.metric("Options buying power", money(account.options_buying_power))
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Cash", money(account.cash))
    c6.metric("Starting balance (setting)", money(settings.starting_balance))
    c7.metric("Options level", account.options_trading_level if account.options_trading_level is not None else "n/a")
    c8.metric("Account", account.account_number_masked)
    if account.trading_blocked or account.account_blocked:
        st.warning("Alpaca reports this account as blocked.")
    if st.button("Refresh"):
        st.rerun()

st.subheader("Local database")
with session_scope(sessions) as session:
    st.write({name: count for name, count in table_counts(session).items()})
    signals = [
        {"time": s.created_at, "symbol": s.underlying_symbol, "direction": s.direction.value,
         "price": s.underlying_price, "rsi_14": s.rsi_14, "reason": s.reason}
        for s in recent_signals(session)
    ]
    positions = [
        {"contract": p.option_symbol, "qty": p.quantity, "avg_entry": p.avg_entry_price,
         "unrealized_pl": p.unrealized_pl}
        for p in open_positions(session)
    ]
    trades = [
        {"contract": t.option_symbol, "qty": t.quantity, "entry": t.entry_price, "exit": t.exit_price,
         "realized_pl": t.realized_pl, "exit_reason": t.exit_reason}
        for t in recent_trades(session)
    ]

for label, rows in (("Signals", signals), ("Positions", positions), ("Trades", trades)):
    st.markdown(f"**{label}**")
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch")
    else:
        st.caption(f"No {label.lower()} yet. Stage 1 doesn't generate any.")
