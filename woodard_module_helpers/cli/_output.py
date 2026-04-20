"""Shared output helpers — switches between human text and machine JSON.

Each verb threads a `json_output: bool` through its implementation. Human
`typer.echo(...)` calls are gated on `not json_output`; at the end, a single
`emit_success(...)` or `emit_error(...)` writes the final structured output.
"""

import json

import typer


def emit_success(verb: str, *, json_output: bool, **fields) -> None:
    """End a verb successfully. In JSON mode, writes one JSON blob to stdout."""
    if json_output:
        payload = {"status": "ok", "verb": verb, **fields}
        typer.echo(json.dumps(payload))


def emit_error(
    verb: str, error: str, *, json_output: bool, exit_code: int = 1
) -> None:
    """End a verb with an error. JSON mode: payload on stdout. Text: msg on stderr."""
    if json_output:
        payload = {"status": "error", "verb": verb, "error": error}
        typer.echo(json.dumps(payload))
    else:
        typer.echo(error, err=True)
    raise typer.Exit(code=exit_code)


def echo(message: str, *, json_output: bool) -> None:
    """Echo human-readable progress unless --json suppresses it."""
    if not json_output:
        typer.echo(message)
