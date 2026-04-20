import typer

from woodard_module_helpers.cli import app


@app.command("request-prod")
def request_prod() -> None:
    """Open a PR from dev to main to graduate to prod."""
    typer.echo("not yet implemented")
    raise typer.Exit(code=1)
