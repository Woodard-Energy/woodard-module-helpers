from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Standard env vars injected into every module by the platform.

    Defaults allow local dev without any env vars set. Production values are
    seeded by `register-module.sh` into the per-slot env file on the VM
    (`/opt/woodard/modules/<slug>/<slot>/.env`).

    The platform injects identity as ``WOODARD_*`` (``WOODARD_SLUG``,
    ``WOODARD_DOMAIN``, ``WOODARD_SLOT``) — see ``auth-and-deploy.md`` and
    ``register-module.sh``. The fields below keep their ``module_*`` names so
    module code (``settings.module_slot`` etc.) is unchanged, but they read
    from the real ``WOODARD_*`` env vars via ``validation_alias``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ``module_name`` resolves to the slug (``<domain>-<name>``); the platform
    # injects no bare-name var, so ``WOODARD_SLUG`` is the only identity string.
    module_name: str = Field("", validation_alias="WOODARD_SLUG")
    module_domain: str = Field("", validation_alias="WOODARD_DOMAIN")
    module_slot: str = Field("dev", validation_alias="WOODARD_SLOT")
    forwarded_prefix: str = ""
    port: int = 8000
    database_url: str = ""
    sql_schema: str = ""
    # SQL Server warehouse write-back — set per write-back module.
    # Combine sql_server/sql_database via build_mssql_url() and pass
    # sql_mi_client_id to get_engine(url, mi_client_id=...). See
    # data-storage-patterns in the modules workspace.
    sql_server: str = ""
    sql_database: str = ""
    sql_mi_client_id: str = ""
    # Azure Database for PostgreSQL — Alembic migrations via managed identity
    # (e.g. the geology stack). pg_host triggers the Postgres migration path.
    # The admin role/identity (DDL) is deliberately separate from the app's
    # runtime read role, so set pg_admin_* for migrations only (CI injects them);
    # pg_schema is the module-owned schema that holds alembic_version.
    pg_host: str = ""
    pg_db: str = ""
    pg_schema: str = ""
    pg_admin_user: str = ""
    pg_admin_mi_client_id: str = ""
    woodard_signing_secret: str = ""
