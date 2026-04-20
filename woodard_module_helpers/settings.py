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
    woodard_signing_secret: str = ""
