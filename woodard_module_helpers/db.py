import os
import struct
from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache
from urllib.parse import quote_plus

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# ODBC connection attribute that carries a pre-fetched Microsoft Entra access
# token (msodbcsql's SQL_COPT_SS_ACCESS_TOKEN).
_SQL_COPT_SS_ACCESS_TOKEN = 1256
_AZURE_SQL_SCOPE = "https://database.windows.net/.default"


def build_mssql_url(server: str, database: str) -> str:
    """Build a SQLAlchemy ``mssql+pyodbc`` URL for `server`/`database`.

    No authentication is embedded — pair it with
    ``get_engine(url, mi_client_id=...)`` so a managed-identity token is
    injected per connection.
    """
    if not server or not database:
        raise ValueError("server and database are required")
    odbc = (
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server={server};Database={database};"
        "Encrypt=yes;TrustServerCertificate=yes"
    )
    return "mssql+pyodbc:///?odbc_connect=" + quote_plus(odbc)


def _attach_managed_identity_token(engine: Engine, client_id: str) -> None:
    """Inject an Entra access token on every connect for a user-assigned
    managed identity.

    The ODBC driver's ``Authentication=ActiveDirectoryManagedIdentity`` mode is
    unreliable on Linux (older builds reject the keyword; the legacy MSI keyword
    only targets system-assigned identities), so we fetch the token via
    ``azure-identity`` and hand it to the driver through the access-token
    attribute — the supported, version-independent path. ``azure-identity`` is
    an optional dependency: install ``woodard-module-helpers[mssql]``.
    """
    from azure.identity import ManagedIdentityCredential

    credential = ManagedIdentityCredential(client_id=client_id)

    @event.listens_for(engine, "do_connect")
    def _provide_token(dialect, conn_rec, cargs, cparams):
        token = credential.get_token(_AZURE_SQL_SCOPE).token.encode("utf-16-le")
        cparams["attrs_before"] = {
            _SQL_COPT_SS_ACCESS_TOKEN: struct.pack(f"<I{len(token)}s", len(token), token)
        }


@lru_cache(maxsize=16)
def get_engine(database_url: str, mi_client_id: str = "") -> Engine:
    """Return a cached SQLAlchemy Engine for `database_url`.

    Same args → same engine (caches up to 16, above any realistic per-module
    need). For SQL Server with a user-assigned managed identity, pass
    `mi_client_id` (and an ``mssql+pyodbc`` URL — see `build_mssql_url`): the
    engine then injects a fresh Entra access token on every connect. For SQLite
    and other URLs, omit it and auth is whatever the URL specifies.
    """
    if not database_url:
        raise ValueError("database_url is required")
    engine = create_engine(database_url, pool_pre_ping=True, future=True)
    if mi_client_id and database_url.startswith("mssql"):
        _attach_managed_identity_token(engine, mi_client_id)
    return engine


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
