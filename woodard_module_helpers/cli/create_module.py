import typer

from woodard_module_helpers.cli import app


@app.command("create-module")
def create_module() -> None:
    """Scaffold a new platform module from the template."""
    typer.echo("not yet implemented")
    raise typer.Exit(code=1)
