from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Standard env vars injected into every module by the platform.

    Defaults allow local dev without any env vars set. Production values
    come from `/etc/woodard/<slug>.<slot>.env` on the VM.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    module_name: str = ""
    module_domain: str = ""
    module_slot: str = "dev"
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
