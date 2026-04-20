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
    """FastAPI dependency — yields a session, closes after the request.

    Usage:
        def _sess():
            yield from session_dep(engine=my_engine)

        @app.get("/things")
        def list_things(s: Session = Depends(_sess)):
            ...
    """
    if engine is None:
        engine = get_engine(os.environ.get("DATABASE_URL", ""))
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


_SCHEMA = os.environ.get("SQL_SCHEMA", "")


class SchemaBase(DeclarativeBase):
    """DeclarativeBase that applies SQL_SCHEMA from env to every subclass table.

    Module models inherit from this instead of DeclarativeBase. Keeps table
    metadata schema-scoped so modules share a database without colliding.
    """

    __abstract__ = True
    if _SCHEMA:
        __table_args__ = {"schema": _SCHEMA}
