from typer.testing import CliRunner

from woodard_module_helpers.cli import app


def test_cli_help_lists_verbs():
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for verb in ("create-module", "push-dev", "request-prod", "convert-to-platform"):
        assert verb in result.stdout


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    from woodard_module_helpers import __version__
    assert __version__ in result.stdout
