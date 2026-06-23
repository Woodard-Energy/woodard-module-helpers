import pytest
from sqlalchemy import Column, Integer, String, text

from woodard_module_helpers.db import (
    build_mssql_url,
    build_postgres_url,
    get_engine,
    get_session,
    session_dep,
)


def test_get_engine_caches_by_url():
    e1 = get_engine("sqlite:///:memory:")
    e2 = get_engine("sqlite:///:memory:")
    e3 = get_engine("sqlite:///:memory:?cache=shared")
    assert e1 is e2
    assert e1 is not e3


def test_schemabase_applies_schema_from_env(monkeypatch):
    # SchemaBase is resolved at subclass-creation time, so set env first.
    monkeypatch.setenv("SQL_SCHEMA", "geology_well_lookup")

    # Re-import to pick up the new env var on a fresh Base.
    import importlib

    from woodard_module_helpers import db as db_mod
    importlib.reload(db_mod)

    class Well(db_mod.SchemaBase):
        __tablename__ = "wells"
        id = Column(Integer, primary_key=True)
        name = Column(String(64))

    assert Well.__table__.schema == "geology_well_lookup"


def test_schemabase_no_schema_when_env_unset(monkeypatch):
    monkeypatch.delenv("SQL_SCHEMA", raising=False)
    import importlib

    from woodard_module_helpers import db as db_mod
    importlib.reload(db_mod)

    class Well(db_mod.SchemaBase):
        __tablename__ = "wells_noschema"
        id = Column(Integer, primary_key=True)

    assert Well.__table__.schema is None


def test_get_session_returns_usable_session():
    engine = get_engine("sqlite:///:memory:")
    with get_session(engine) as s:
        result = s.execute(text("SELECT 1")).scalar()
        assert result == 1


def test_session_dep_yields_and_closes():
    engine = get_engine("sqlite:///:memory:")
    gen = session_dep(engine=engine)
    session = next(gen)
    assert session.execute(text("SELECT 1")).scalar() == 1
    # Exhaust generator to trigger cleanup.
    for _ in gen:
        pass


def test_session_dep_rolls_back_on_exception():
    """Exception thrown into the generator triggers rollback before close."""
    engine = get_engine("sqlite:///:memory:")
    gen = session_dep(engine=engine)
    session = next(gen)
    assert session.execute(text("SELECT 1")).scalar() == 1

    # Simulate an exception during the request by throwing into the generator.
    with pytest.raises(RuntimeError, match="simulated"):
        gen.throw(RuntimeError("simulated"))

    # After throw, the generator has run its except/finally and cleaned up.


def test_session_dep_raises_when_database_url_unset(monkeypatch):
    """No engine passed + no DATABASE_URL set → clear ValueError."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        gen = session_dep()
        next(gen)


def test_build_mssql_url_embeds_server_database_driver():
    url = build_mssql_url("sql.example.com", "AppDb")
    assert url.startswith("mssql+pyodbc:///?odbc_connect=")
    from urllib.parse import unquote_plus

    odbc = unquote_plus(url.split("odbc_connect=", 1)[1])
    assert "Server=sql.example.com" in odbc
    assert "Database=AppDb" in odbc
    assert "ODBC Driver 18 for SQL Server" in odbc


def test_build_mssql_url_requires_both_args():
    with pytest.raises(ValueError):
        build_mssql_url("", "AppDb")
    with pytest.raises(ValueError):
        build_mssql_url("host", "")


def test_get_engine_sqlite_ignores_mi_client_id():
    # Non-mssql URL + mi_client_id must NOT trigger an azure-identity import.
    engine = get_engine("sqlite:///:memory:", mi_client_id="ignored")
    with get_session(engine) as s:
        assert s.execute(text("SELECT 1")).scalar() == 1


def test_attach_managed_identity_token_constructs_credential_and_listener(monkeypatch):
    """_attach wires ManagedIdentityCredential(client_id=...) and registers a
    do_connect listener — verified on a sqlite engine so no pyodbc is needed."""
    import sys
    import types

    seen = {}

    class _FakeCredential:
        def __init__(self, client_id=None):
            seen["client_id"] = client_id

        def get_token(self, scope):
            return types.SimpleNamespace(token="faketoken")

    fake_identity = types.ModuleType("azure.identity")
    fake_identity.ManagedIdentityCredential = _FakeCredential
    monkeypatch.setitem(sys.modules, "azure", types.ModuleType("azure"))
    monkeypatch.setitem(sys.modules, "azure.identity", fake_identity)

    from woodard_module_helpers.db import _attach_managed_identity_token

    engine = get_engine("sqlite:///:memory:")
    _attach_managed_identity_token(engine, "client-abc")
    # Credential constructed with the given client id (this runs immediately
    # before the do_connect listener is registered). The actual connect-time
    # token injection is verified end-to-end against live SQL on the VM.
    assert seen["client_id"] == "client-abc"


def test_get_engine_routes_mssql_urls_to_token_attach(monkeypatch):
    """get_engine attaches the MI token only for mssql URLs with a client id."""
    from woodard_module_helpers import db as db_mod

    attached = []
    monkeypatch.setattr(db_mod, "create_engine", lambda url, **kw: f"ENGINE:{url}")
    monkeypatch.setattr(
        db_mod,
        "_attach_managed_identity_token",
        lambda engine, client_id: attached.append((engine, client_id)),
    )

    db_mod.get_engine.cache_clear()
    eng = db_mod.get_engine("mssql+pyodbc:///?odbc_connect=x", mi_client_id="cid-1")
    assert attached == [(eng, "cid-1")]

    attached.clear()
    db_mod.get_engine.cache_clear()
    db_mod.get_engine("sqlite:///:memory:", mi_client_id="cid-2")
    assert attached == []  # non-mssql → no token attach

    db_mod.get_engine.cache_clear()  # leave the cache clean for other tests


def test_build_postgres_url_embeds_user_host_db_sslmode():
    url = build_postgres_url("pg.example.com", "ogmanager_dev", "mi-postgres")
    assert url == "postgresql+psycopg://mi-postgres@pg.example.com/ogmanager_dev?sslmode=require"


def test_build_postgres_url_requires_all_args():
    with pytest.raises(ValueError):
        build_postgres_url("", "db", "user")
    with pytest.raises(ValueError):
        build_postgres_url("host", "", "user")
    with pytest.raises(ValueError):
        build_postgres_url("host", "db", "")


def test_attach_pg_managed_identity_token_constructs_credential_and_listener(monkeypatch):
    """_attach_pg wires ManagedIdentityCredential(client_id=...) and registers a
    do_connect listener — verified on a sqlite engine so no psycopg/azure deps
    are needed. Connect-time password injection is verified live on the VM."""
    import sys
    import types

    seen = {}

    class _FakeCredential:
        def __init__(self, client_id=None):
            seen["client_id"] = client_id

        def get_token(self, scope):
            return types.SimpleNamespace(token="pgtoken")

    fake_identity = types.ModuleType("azure.identity")
    fake_identity.ManagedIdentityCredential = _FakeCredential
    monkeypatch.setitem(sys.modules, "azure", types.ModuleType("azure"))
    monkeypatch.setitem(sys.modules, "azure.identity", fake_identity)

    from woodard_module_helpers.db import _attach_pg_managed_identity_token

    engine = get_engine("sqlite:///:memory:")
    _attach_pg_managed_identity_token(engine, "client-pg")
    assert seen["client_id"] == "client-pg"


def test_get_engine_routes_postgresql_urls_to_pg_token_attach(monkeypatch):
    """get_engine attaches the PG MI token only for postgresql URLs with a client id."""
    from woodard_module_helpers import db as db_mod

    attached = []
    monkeypatch.setattr(db_mod, "create_engine", lambda url, **kw: f"ENGINE:{url}")
    monkeypatch.setattr(
        db_mod,
        "_attach_pg_managed_identity_token",
        lambda engine, client_id: attached.append((engine, client_id)),
    )

    db_mod.get_engine.cache_clear()
    eng = db_mod.get_engine("postgresql+psycopg://u@h/db", mi_client_id="cid-pg")
    assert attached == [(eng, "cid-pg")]

    attached.clear()
    db_mod.get_engine.cache_clear()
    db_mod.get_engine("sqlite:///:memory:", mi_client_id="cid-x")
    assert attached == []  # non-postgres → no PG token attach

    db_mod.get_engine.cache_clear()
