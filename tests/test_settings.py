import pytest
from woodard_module_helpers.settings import Settings


def test_settings_defaults_when_env_empty(monkeypatch):
    for k in [
        "MODULE_NAME", "MODULE_DOMAIN", "MODULE_SLOT",
        "FORWARDED_PREFIX", "PORT", "DATABASE_URL",
        "SQL_SCHEMA", "WOODARD_SIGNING_SECRET",
    ]:
        monkeypatch.delenv(k, raising=False)
    s = Settings()
    assert s.module_name == ""
    assert s.module_domain == ""
    assert s.module_slot == "dev"
    assert s.forwarded_prefix == ""
    assert s.port == 8000
    assert s.database_url == ""
    assert s.sql_schema == ""
    assert s.woodard_signing_secret == ""


def test_settings_reads_env(monkeypatch):
    monkeypatch.setenv("MODULE_NAME", "well-lookup")
    monkeypatch.setenv("MODULE_DOMAIN", "geology")
    monkeypatch.setenv("MODULE_SLOT", "prod")
    monkeypatch.setenv("FORWARDED_PREFIX", "/geology/well-lookup")
    monkeypatch.setenv("PORT", "8101")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./data/app.db")
    monkeypatch.setenv("SQL_SCHEMA", "geology_well_lookup")
    monkeypatch.setenv("WOODARD_SIGNING_SECRET", "s3cret")
    s = Settings()
    assert s.module_name == "well-lookup"
    assert s.module_domain == "geology"
    assert s.module_slot == "prod"
    assert s.forwarded_prefix == "/geology/well-lookup"
    assert s.port == 8101
    assert s.database_url == "sqlite:///./data/app.db"
    assert s.sql_schema == "geology_well_lookup"
    assert s.woodard_signing_secret == "s3cret"
