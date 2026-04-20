import subprocess
from pathlib import Path


def test_cli_help_end_to_end():
    """Installed package exposes `woodard-cli --help` via entry point."""
    result = subprocess.run(
        ["uv", "run", "woodard-cli", "--help"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0, result.stderr
    for verb in ("create-module", "push-dev", "request-prod", "convert-to-platform"):
        assert verb in result.stdout


def test_cli_version_end_to_end():
    result = subprocess.run(
        ["uv", "run", "woodard-cli", "--version"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )
    assert result.returncode == 0
    # Read version from package to avoid hardcoding.
    from woodard_module_helpers import __version__
    assert __version__ in result.stdout


def test_all_public_api_importable():
    """Simulate what a downstream module repo does: import everything."""
    import woodard_module_helpers as wmh

    # Exercise each export is callable / instantiable.
    assert wmh.Settings()
    assert callable(wmh.prefix)
    assert callable(wmh.current_user)
    assert callable(wmh.require_role("reserves"))
    assert callable(wmh.require_any_role("reserves", "land"))
    assert wmh.__version__
