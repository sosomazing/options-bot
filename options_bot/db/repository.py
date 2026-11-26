"""Small, readable helpers for saving and loading rows.

Keeping database code here means the strategy code later can say
``record_signal(...)`` instead of writing SQL.
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from options_bot.db.models import Order, Position, Signal, Trade


def record_signal(session: Session, **fields) -> Signal:
    signal = Signal(**fields)
    session.add(signal)
    session.flush()  # assigns signal.id without committing yet
    return signal


def recent_signals(session: Session, limit: int = 50) -> Sequence[Signal]:
    stmt = select(Signal).order_by(Signal.created_at.desc(), Signal.id.desc()).limit(limit)
    return session.scalars(stmt).all()


def open_positions(session: Session) -> Sequence[Position]:
    return session.scalars(select(Position).order_by(Position.opened_at)).all()


def recent_trades(session: Session, limit: int = 50) -> Sequence[Trade]:
    stmt = select(Trade).order_by(Trade.entry_time.desc(), Trade.id.desc()).limit(limit)
    return session.scalars(stmt).all()


def table_counts(session: Session) -> dict[str, int]:
    return {
        model.__tablename__: session.scalar(select(func.count()).select_from(model)) or 0
        for model in (Signal, Order, Position, Trade)
    }
