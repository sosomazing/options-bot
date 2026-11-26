"""Database tables, written as Python classes (SQLAlchemy "models").

Each class below is one table in the SQLite file. Each attribute is a column.

* ``Signal``   - a moment the strategy said "this looks like a CALL/PUT setup",
                 with the indicator values (VWAP, EMA 9/21, RSI 14, volume) behind it.
* ``Order``    - an order the bot *would* send. In stage 1 nothing creates these;
                 the table is ready for later stages.
* ``Position`` - an option contract currently held (one row per contract symbol).
* ``Trade``    - a finished round trip: entry, exit and profit/loss.

Safety: ``Order``, ``Position`` and ``Trade`` have an ``is_paper`` column, and
the database itself refuses any row where it isn't true (a CHECK constraint).

Money is stored as ``Numeric`` with 4 decimal places and read back as Python
``Decimal``, so $1.10 stays exactly $1.10 instead of 1.1000000000000001.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Money(TypeDecorator):
    """Exact money in SQLite: stored as text like '1.1000', returned as Decimal.

    SQLite has no real decimal type, so plain ``Numeric`` would round-trip
    through floats. Text keeps every digit.
    """

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return str(Decimal(str(value)).quantize(Decimal("0.0001")))

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


class Base(DeclarativeBase):
    pass


class SignalDirection(str, enum.Enum):
    CALL = "CALL"   # expecting the stock to go up
    PUT = "PUT"     # expecting the stock to go down


class OrderSide(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, enum.Enum):
    # Mirrors the main Alpaca order statuses we'll care about later.
    PENDING = "pending"     # created locally, not sent
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"


def _enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    underlying_symbol: Mapped[str] = mapped_column(String(16), index=True)   # e.g. "SPY"
    direction: Mapped[SignalDirection] = mapped_column(_enum(SignalDirection, "signal_direction"))
    strategy_name: Mapped[str] = mapped_column(String(64), default="vwap_ema_rsi_volume")

    # Indicator snapshot at the moment of the signal.
    underlying_price: Mapped[Decimal] = mapped_column(Money)
    vwap: Mapped[Decimal | None] = mapped_column(Money)
    ema_9: Mapped[Decimal | None] = mapped_column(Money)
    ema_21: Mapped[Decimal | None] = mapped_column(Money)
    rsi_14: Mapped[Decimal | None] = mapped_column(Money)
    volume: Mapped[int | None] = mapped_column(Integer)

    reason: Mapped[str | None] = mapped_column(Text)
    acted_on: Mapped[bool] = mapped_column(Boolean, default=False)

    orders: Mapped[list[Order]] = relationship(back_populates="signal")

    __table_args__ = (
        CheckConstraint("CAST(underlying_price AS REAL) > 0", name="ck_signal_price_positive"),
        CheckConstraint("rsi_14 IS NULL OR CAST(rsi_14 AS REAL) BETWEEN 0 AND 100", name="ck_signal_rsi_range"),
        CheckConstraint("volume IS NULL OR volume >= 0", name="ck_signal_volume_nonneg"),
    )

    def __repr__(self) -> str:
        return f"Signal(id={self.id}, {self.underlying_symbol} {self.direction.value if self.direction else None})"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id", ondelete="SET NULL"))

    # Our own unique ID (Alpaca's client_order_id), so we never double-send.
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), unique=True)

    option_symbol: Mapped[str] = mapped_column(String(32), index=True)  # OCC symbol, e.g. SPY241220C00480000
    underlying_symbol: Mapped[str] = mapped_column(String(16))
    side: Mapped[OrderSide] = mapped_column(_enum(OrderSide, "order_side"))
    quantity: Mapped[int] = mapped_column(Integer)
    order_type: Mapped[str] = mapped_column(String(16), default="limit")
    limit_price: Mapped[Decimal | None] = mapped_column(Money)
    status: Mapped[OrderStatus] = mapped_column(_enum(OrderStatus, "order_status"), default=OrderStatus.PENDING)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    filled_avg_price: Mapped[Decimal | None] = mapped_column(Money)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True)

    signal: Mapped[Signal | None] = relationship(back_populates="orders")

    __table_args__ = (
        CheckConstraint("is_paper = 1", name="ck_order_paper_only"),
        CheckConstraint("quantity > 0", name="ck_order_quantity_positive"),
        CheckConstraint("limit_price IS NULL OR CAST(limit_price AS REAL) > 0", name="ck_order_limit_positive"),
    )


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    option_symbol: Mapped[str] = mapped_column(String(32), unique=True)
    underlying_symbol: Mapped[str] = mapped_column(String(16), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    avg_entry_price: Mapped[Decimal] = mapped_column(Money)
    current_price: Mapped[Decimal | None] = mapped_column(Money)
    unrealized_pl: Mapped[Decimal | None] = mapped_column(Money)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        CheckConstraint("is_paper = 1", name="ck_position_paper_only"),
        CheckConstraint("quantity != 0", name="ck_position_quantity_nonzero"),
    )


# Money columns are stored as text, so CHECK rules on them use CAST(... AS REAL).


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    option_symbol: Mapped[str] = mapped_column(String(32), index=True)
    underlying_symbol: Mapped[str] = mapped_column(String(16), index=True)
    quantity: Mapped[int] = mapped_column(Integer)

    entry_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    exit_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    entry_price: Mapped[Decimal] = mapped_column(Money)
    exit_price: Mapped[Decimal | None] = mapped_column(Money)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    realized_pl: Mapped[Decimal | None] = mapped_column(Money)
    exit_reason: Mapped[str | None] = mapped_column(String(64))  # e.g. "target", "stop", "end_of_day"
    is_paper: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        CheckConstraint("is_paper = 1", name="ck_trade_paper_only"),
        CheckConstraint("quantity > 0", name="ck_trade_quantity_positive"),
        CheckConstraint("CAST(entry_price AS REAL) > 0", name="ck_trade_entry_positive"),
    )
