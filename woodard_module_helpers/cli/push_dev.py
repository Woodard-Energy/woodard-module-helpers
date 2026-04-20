import typer

from woodard_module_helpers.cli import app


@app.command("push-dev")
def push_dev() -> None:
    """Commit + push to dev branch and poll dev slot health."""
    typer.echo("not yet implemented")
    raise typer.Exit(code=1)
