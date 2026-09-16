"""Database engine and session management.

Synchronous SQLAlchemy, deliberately. At under 100 units/day the concurrency
argument for async is irrelevant, while sharing one set of models and one
session idiom between the FastAPI app and the RQ workers removes a whole class
of duplicated data-access code. FastAPI runs sync path operations in a
threadpool, so the event loop is not blocked.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_settings = get_settings()

engine: Engine = create_engine(
    _settings.database_url,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_max_overflow,
    pool_pre_ping=True,
    echo=_settings.db_echo,
    future=True,
    connect_args={"application_name": "caready-api"},
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@event.listens_for(engine, "connect")
def _set_session_defaults(dbapi_connection, connection_record) -> None:  # noqa: ANN001
    """Fail fast rather than hang on a lock.

    A request that waits indefinitely on a row lock is worse than one that
    errors: it ties up a worker and gives the user no feedback. These are
    generous relative to normal query time and tight relative to a hung
    transaction.
    """
    with dbapi_connection.cursor() as cur:
        cur.execute("SET statement_timeout = '30s'")
        cur.execute("SET idle_in_transaction_session_timeout = '60s'")
        cur.execute("SET lock_timeout = '10s'")


def get_db() -> Iterator[Session]:
    """FastAPI dependency. One session per request, rolled back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Session for workers and scripts, outside the request lifecycle."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def append_only_purge_allowed(session: Session) -> Iterator[None]:
    """Temporarily permit DELETE on append-only tables.

    The only legitimate caller is the PDP retention purge job. Scoped to the
    current transaction, so the permission cannot leak into unrelated work.
    """
    session.execute(text("SET LOCAL caready.allow_append_only_purge = 'on'"))
    try:
        yield
    finally:
        session.execute(text("SET LOCAL caready.allow_append_only_purge = 'off'"))


def check_database() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - health check reports, never raises
        return False
