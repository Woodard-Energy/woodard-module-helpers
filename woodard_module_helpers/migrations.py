"""Alembic support for write-back modules.

A module's ``alembic/env.py`` is two lines — import its metadata and call
``run_migrations(metadata)``; this module builds the engine from ``Settings``
(managed-identity for SQL Server, SQLite otherwise) and keeps each module's
``alembic_version`` table inside its own schema.

At startup the module's ``main.py`` calls ``upgrade_head(module_root)`` (SQL
path only — SQLite modules keep ``SchemaBase.metadata.create_all``).

``alembic`` is an optional dependency (imported lazily) — install
``woodard-module-helpers[mssql]``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def alembic_config(module_root: str | Path) -> Any:
    """Build an Alembic ``Config`` for a module, with an absolute
    ``script_location`` so it resolves regardless of the process working dir
    (systemd starts units from ``/``)."""
    from alembic.config import Config

    root = Path(module_root)
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    return cfg


def upgrade_head(module_root: str | Path) -> None:
    """Apply all pending migrations. Call once at startup for the SQL path."""
    from alembic import command

    command.upgrade(alembic_config(module_root), "head")


def run_migrations(target_metadata: Any) -> None:
    """Run migrations from inside a module's ``alembic/env.py``.

    Online (the normal path for ``upgrade`` and ``--autogenerate``) builds the
    engine from ``Settings`` — managed-identity for SQL Server, SQLite fallback —
    and places ``alembic_version`` in the module's schema. Offline (``--sql``)
    emits script text without connecting.
    """
    from alembic import context

    from woodard_module_helpers.db import build_mssql_url, get_engine
    from woodard_module_helpers.settings import Settings

    s = Settings()
    if s.sql_server:
        url = build_mssql_url(s.sql_server, s.sql_database)
        version_schema = s.sql_schema or None
    else:
        url = s.database_url or "sqlite:///./data/app.db"
        version_schema = None

    common = dict(
        target_metadata=target_metadata,
        version_table_schema=version_schema,
        include_schemas=bool(version_schema),
        compare_type=True,
    )

    if context.is_offline_mode():
        context.configure(
            url=url,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
            **common,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = get_engine(url, mi_client_id=s.sql_mi_client_id) if s.sql_server else get_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, **common)
        with context.begin_transaction():
            context.run_migrations()
