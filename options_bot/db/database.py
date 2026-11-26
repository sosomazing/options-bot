"""Database connection: opens the SQLite file and hands out sessions.

* ``make_engine()``  opens (or creates) the SQLite file.
* ``init_db()``      creates the tables if they don't exist yet. Safe to run
                     every start-up: it never deletes data.
* ``session_scope()`` gives you a "session" (a unit of work). If your code
                     finishes normally the changes are saved (commit); if it
                     raises, they're undone (rollback).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from options_bot.config import PROJECT_ROOT
from options_bot.db.models import Base
from options_bot.errors import ConfigError

log = logging.getLogger(__name__)


def _resolve_sqlite_url(database_url: str) -> str:
    """Make relative paths relative to the project folder, and create the folder."""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ConfigError("Only SQLite databases are supported in stage 1.")
    if url.database in (None, "", ":memory:"):
        return database_url
    path = Path(url.database)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return url.set(database=str(path)).render_as_string(hide_password=False)


def make_engine(database_url: str, echo: bool = False) -> Engine:
    engine = create_engine(_resolve_sqlite_url(database_url), echo=echo, future=True)

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - trivial
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")   # enforce links between tables
        cursor.execute("PRAGMA journal_mode=WAL")  # dashboard can read while the bot writes
        cursor.close()

    return engine


def init_db(engine: Engine) -> None:
    try:
        Base.metadata.create_all(engine)
    except SQLAlchemyError:
        log.exception("Could not create database tables")
        raise
    log.info("Database ready: %s", engine.url.database)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        log.exception("Database transaction rolled back")
        raise
    finally:
        session.close()
