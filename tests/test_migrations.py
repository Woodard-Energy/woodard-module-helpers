from woodard_module_helpers.migrations import alembic_config, upgrade_head


def test_alembic_config_uses_absolute_module_script_location(tmp_path):
    (tmp_path / "alembic.ini").write_text("[alembic]\n")
    cfg = alembic_config(tmp_path)
    assert cfg.get_main_option("script_location") == str(tmp_path / "alembic")


def test_upgrade_head_invokes_alembic_upgrade_to_head(tmp_path, monkeypatch):
    (tmp_path / "alembic.ini").write_text("[alembic]\n")
    seen = {}

    import alembic.command as command

    monkeypatch.setattr(
        command,
        "upgrade",
        lambda cfg, rev: seen.update(rev=rev, loc=cfg.get_main_option("script_location")),
    )
    upgrade_head(tmp_path)
    assert seen["rev"] == "head"
    assert seen["loc"] == str(tmp_path / "alembic")


def test_run_migrations_is_importable_without_calling(tmp_path):
    # Importing the module must not require alembic at import time (lazy imports);
    # run_migrations only makes sense inside an alembic env, exercised live.
    from woodard_module_helpers import run_migrations, upgrade_head  # noqa: F401
