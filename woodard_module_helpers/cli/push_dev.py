import time
from pathlib import Path

import httpx
import typer

from woodard_module_helpers.cli import app
from woodard_module_helpers.cli._output import echo, emit_error, emit_success
from woodard_module_helpers.cli._shell import CommandError, run

DEV_BASE = "https://wip-dev.woodardenergy.com"


class HealthPollTimeout(RuntimeError):
    """Raised when /_health never reports the expected version in time."""


@app.command("push-dev")
def push_dev(
    message: str = typer.Option("wip", "--message", "-m"),
    skip_tests: bool = typer.Option(False, "--skip-tests"),
    poll_timeout: int = typer.Option(120, "--poll-timeout"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Run tests locally, commit, push to dev, and poll dev slot health."""
    verb = "push-dev"
    slug, domain, version = _read_module_yaml()
    module_name = slug.split("-", 1)[1]

    if not skip_tests:
        echo("Running local tests...", json_output=json_output)
        try:
            run(["uv", "run", "pytest", "-q"])
        except CommandError as e:
            emit_error(
                verb, f"tests failed, not pushing: {e.stderr}",
                json_output=json_output,
            )

    echo("Committing + pushing to dev...", json_output=json_output)
    try:
        run(["git", "add", "-A"])
        run(["git", "commit", "-m", message], check=False)
        run(["git", "push", "origin", "dev"])
    except CommandError as e:
        emit_error(verb, f"git failed: {e.stderr}", json_output=json_output)

    health_url = f"{DEV_BASE}/{domain}/{module_name}/_health"
    dev_url = f"{DEV_BASE}/{domain}/{module_name}/"
    echo(
        f"Polling {health_url} for version {version}...",
        json_output=json_output,
    )

    try:
        result = _poll_health(
            health_url, expected_version=version, timeout_s=poll_timeout
        )
    except HealthPollTimeout as e:
        emit_error(verb, str(e), json_output=json_output)

    echo(
        f"✓ dev slot healthy at version {result['version']}",
        json_output=json_output,
    )
    echo(f"  {dev_url}", json_output=json_output)

    emit_success(
        verb,
        json_output=json_output,
        slug=slug,
        version=result["version"],
        dev_url=dev_url,
    )


def _read_module_yaml() -> tuple[str, str, str]:
    path = Path("module.yaml")
    if not path.exists():
        typer.echo("module.yaml not found in current directory", err=True)
        raise typer.Exit(code=2)

    fields: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if ":" in line and not line.startswith("#"):
            k, _, v = line.partition(":")
            fields[k.strip()] = v.strip().strip('"').strip("'")

    name = fields.get("name", "")
    domain = fields.get("domain", "")
    version = fields.get("version", "0.0.0")
    if not name or not domain:
        typer.echo("module.yaml missing name or domain", err=True)
        raise typer.Exit(code=2)
    return f"{domain}-{name}", domain, version


def _poll_health(
    url: str, expected_version: str, timeout_s: int = 120
) -> dict:
    deadline = time.time() + timeout_s
    last_seen: dict | None = None
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=5)
            if r.status_code == 200:
                body = r.json()
                last_seen = body
                if body.get("version") == expected_version:
                    return body
        except httpx.RequestError:
            pass
        time.sleep(2)
    raise HealthPollTimeout(
        f"timeout after {timeout_s}s; last seen: {last_seen}"
    )
