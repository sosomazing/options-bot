"""Database: tables are created, rows save and load, safety rules hold."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError, StatementError

from options_bot.db import (
    Order, OrderSide, OrderStatus, Position, Signal, SignalDirection, Trade,
    init_db, make_engine, make_session_factory, session_scope,
)
from options_bot.db.repository import open_positions, recent_signals, recent_trades, record_signal, table_counts


@pytest.fixture
def sessions(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    init_db(engine)
    yield make_session_factory(engine)
    engine.dispose()


def _signal(**overrides):
    fields = dict(underlying_symbol="SPY", direction=SignalDirection.CALL, underlying_price=Decimal("500.12"),
                  vwap=Decimal("499.80"), ema_9=Decimal("500.01"), ema_21=Decimal("499.50"),
                  rsi_14=Decimal("58.3"), volume=125000, reason="price above VWAP, EMA9 > EMA21")
    fields.update(overrides)
    return fields


def test_tables_created(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'x.db'}")
    init_db(engine)
    assert set(inspect(engine).get_table_names()) == {"signals", "orders", "positions", "trades"}
    init_db(engine)  # running twice is safe
    engine.dispose()


def test_relative_path_is_created_under_project(tmp_path, monkeypatch):
    from options_bot.db import database
    monkeypatch.setattr(database, "PROJECT_ROOT", tmp_path)
    engine = make_engine("sqlite:///data/sub/bot.db")
    init_db(engine)
    assert (tmp_path / "data" / "sub" / "bot.db").exists()
    engine.dispose()


def test_signal_round_trip_keeps_exact_money(sessions):
    with session_scope(sessions) as s:
        sig_id = record_signal(s, **_signal(underlying_price=Decimal("1.10"))).id
    with session_scope(sessions) as s:
        sig = s.get(Signal, sig_id)
        assert sig.underlying_price == Decimal("1.1000")
        assert sig.direction is SignalDirection.CALL
        assert sig.created_at is not None
        assert [x.id for x in recent_signals(s)] == [sig_id]


def test_order_position_trade_round_trip(sessions):
    with session_scope(sessions) as s:
        sig = record_signal(s, **_signal())
        entry = Order(signal_id=sig.id, client_order_id="test-entry-1", option_symbol="SPY261127C00500000",
                      underlying_symbol="SPY", side=OrderSide.BUY, quantity=1, limit_price=Decimal("1.25"))
        exit_ = Order(client_order_id="test-exit-1", option_symbol="SPY261127C00500000",
                      underlying_symbol="SPY", side=OrderSide.SELL, quantity=1, limit_price=Decimal("1.60"))
        s.add_all([entry, exit_])
        s.add(Position(option_symbol="SPY261127C00500000", underlying_symbol="SPY", quantity=1,
                       avg_entry_price=Decimal("1.25")))
        s.flush()
        s.add(Trade(option_symbol="SPY261127C00500000", underlying_symbol="SPY", quantity=1,
                    entry_order_id=entry.id, exit_order_id=exit_.id, entry_price=Decimal("1.25"),
                    exit_price=Decimal("1.60"), exit_time=datetime.now(timezone.utc),
                    realized_pl=Decimal("35.00"), exit_reason="target"))
    with session_scope(sessions) as s:
        assert table_counts(s) == {"signals": 1, "orders": 2, "positions": 1, "trades": 1}
        order = s.query(Order).filter_by(client_order_id="test-entry-1").one()
        assert order.status is OrderStatus.PENDING and order.is_paper is True
        assert order.signal.underlying_symbol == "SPY"
        assert open_positions(s)[0].avg_entry_price == Decimal("1.2500")
        assert recent_trades(s)[0].realized_pl == Decimal("35.0000")


@pytest.mark.parametrize("model,fields", [
    (Order, dict(client_order_id="x", option_symbol="O", underlying_symbol="SPY", side=OrderSide.BUY, quantity=1)),
    (Position, dict(option_symbol="O", underlying_symbol="SPY", quantity=1, avg_entry_price=Decimal("1"))),
    (Trade, dict(option_symbol="O", underlying_symbol="SPY", quantity=1, entry_price=Decimal("1"))),
])
def test_database_refuses_non_paper_rows(sessions, model, fields):
    with pytest.raises(IntegrityError):
        with session_scope(sessions) as s:
            s.add(model(is_paper=False, **fields))


@pytest.mark.parametrize("overrides", [
    dict(underlying_price=Decimal("-1")),
    dict(underlying_price=Decimal("0")),
    dict(rsi_14=Decimal("101")),
    dict(volume=-5),
])
def test_signal_checks(sessions, overrides):
    with pytest.raises(IntegrityError):
        with session_scope(sessions) as s:
            record_signal(s, **_signal(**overrides))


def test_bad_enum_value_is_rejected(sessions):
    with pytest.raises((StatementError, LookupError, ValueError)):
        with session_scope(sessions) as s:
            record_signal(s, **_signal(direction="SIDEWAYS"))


def test_duplicate_client_order_id_rejected(sessions):
    fields = dict(option_symbol="O", underlying_symbol="SPY", side=OrderSide.BUY, quantity=1)
    with pytest.raises(IntegrityError):
        with session_scope(sessions) as s:
            s.add_all([Order(client_order_id="dup", **fields), Order(client_order_id="dup", **fields)])


def test_failed_transaction_rolls_back(sessions):
    with pytest.raises(RuntimeError):
        with session_scope(sessions) as s:
            record_signal(s, **_signal())
            raise RuntimeError("boom")
    with session_scope(sessions) as s:
        assert table_counts(s)["signals"] == 0


def test_foreign_keys_enforced(sessions):
    with pytest.raises(IntegrityError):
        with session_scope(sessions) as s:
            s.add(Order(signal_id=999, client_order_id="fk", option_symbol="O", underlying_symbol="SPY",
                        side=OrderSide.BUY, quantity=1))


def test_raw_sql_insert_of_live_order_blocked(sessions):
    with pytest.raises(IntegrityError):
        with session_scope(sessions) as s:
            s.execute(text("INSERT INTO orders (client_order_id, option_symbol, underlying_symbol, side, quantity,"
                           " order_type, status, is_paper, created_at) VALUES ('r','O','SPY','buy',1,'limit',"
                           "'pending',0,'2026-01-01')"))
