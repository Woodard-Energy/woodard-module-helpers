import typer

from woodard_module_helpers import __version__

app = typer.Typer(
    name="woodard-cli",
    help="CLI for creating and deploying Woodard Intelligence Platform modules.",
    no_args_is_help=True,
)


def _version_callback(value: bool):
    if value:
        typer.echo(f"woodard-cli {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True
    ),
):
    """Woodard Intelligence Platform module CLI."""


# Verb registration — each verb module declares its own @app.command().
from woodard_module_helpers.cli import (  # noqa: E402, F401
    clone_module,
    convert_to_platform,
    create_module,
    push_dev,
    request_prod,
)


def main() -> None:
    """Entry point for the `woodard-cli` console script."""
    app()
