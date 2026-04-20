def test_public_api_surface():
    import woodard_module_helpers as wmh

    expected = {
        "Settings",
        "prefix",
        "setup_templates",
        "current_user",
        "require_role",
        "require_any_role",
        "compute_signature",
        "SchemaBase",
        "get_engine",
        "get_session",
        "session_dep",
        "signed_identity_headers",
        "__version__",
    }
    missing = expected - set(dir(wmh))
    assert not missing, f"missing from public API: {missing}"


def test_version_matches_pyproject():
    import tomllib
    from pathlib import Path

    import woodard_module_helpers as wmh

    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    meta = tomllib.loads(pyproject.read_text())
    assert wmh.__version__ == meta["project"]["version"]
