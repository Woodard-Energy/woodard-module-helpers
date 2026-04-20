import typer

from woodard_module_helpers.cli import app


@app.command("convert-to-platform")
def convert_to_platform() -> None:
    """Promote an existing personal-use project to the platform."""
    typer.echo("not yet implemented")
    raise typer.Exit(code=1)
