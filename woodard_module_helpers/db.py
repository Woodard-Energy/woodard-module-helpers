import os
from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


@lru_cache(maxsize=16)
def get_engine(database_url: str) -> Engine:
    """Return a cached SQLAlchemy Engine for `database_url`.

    Same URL → same engine. Different URL → different engine. Caches up to 16
    engines (well above any realistic per-module need).
    """
    if not database_url:
        raise ValueError("database_url is required")
    return create_engine(database_url, pool_pre_ping=True, future=True)


@contextmanager
def get_session(engine: Engine) -> Generator[Session, None, None]:
    """Context-managed session. Commits on success, rolls back on error."""
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def session_dep(engine: Engine | None = None) -> Generator[Session, None, None]:
    """FastAPI dependency — yields a session, rolls back on exception, closes.

    Callers are responsible for committing. On unhandled exceptions during
    the request, rolls back any in-progress transaction before close.

    If `engine` is None, reads `DATABASE_URL` env directly (bypasses Settings).

    Usage:
        def _sess():
            yield from session_dep(engine=my_engine)

        @app.get("/things")
        def list_things(s: Session = Depends(_sess)):
            ...
    """
    if engine is None:
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            raise ValueError(
                "DATABASE_URL env var is not set; pass engine explicitly or set it"
            )
        engine = get_engine(url)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


_SCHEMA = os.environ.get("SQL_SCHEMA", "")


class SchemaBase(DeclarativeBase):
    """DeclarativeBase that applies SQL_SCHEMA from env to every subclass table.

    Module models inherit from this instead of DeclarativeBase. Keeps table
    metadata schema-scoped so modules share a database without colliding.

    **Note:** `SQL_SCHEMA` is read once at import time. If a subclass sets its
    own `__table_args__` (e.g. for constraints), it must include the schema
    dict explicitly — the tuple form silently replaces, not merges:

        class Well(SchemaBase):
            __tablename__ = "wells"
            __table_args__ = (
                UniqueConstraint("api_number"),
                {"schema": os.environ.get("SQL_SCHEMA", "")},  # preserve
            )
    """

    __abstract__ = True
    if _SCHEMA:
        __table_args__ = {"schema": _SCHEMA}
