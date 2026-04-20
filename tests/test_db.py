from sqlalchemy import Column, Integer, String, text

from woodard_module_helpers.db import (
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
