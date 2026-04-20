import re
from pathlib import Path

import typer

from woodard_module_helpers.cli import app
from woodard_module_helpers.cli._output import echo, emit_error, emit_success
from woodard_module_helpers.cli._shell import CommandError, run

VALID_DOMAINS = ("drilling", "geology", "land", "midstream", "reservoir")
TEMPLATE_REPO = "woodard-energy/module-template"
KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


@app.command("create-module")
def create_module(
    domain: str = typer.Option(..., "--domain", "-d"),
    name: str = typer.Option(..., "--name", "-n"),
    display_name: str = typer.Option(..., "--display-name"),
    description: str = typer.Option("", "--description"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Scaffold a new platform module from the template."""
    verb = "create-module"

    if domain not in VALID_DOMAINS:
        emit_error(
            verb,
            f"domain must be one of {VALID_DOMAINS}, got {domain!r}",
            json_output=json_output,
            exit_code=2,
        )
    if not KEBAB_RE.match(name):
        emit_error(
            verb,
            f"name must be kebab-case, got {name!r}",
            json_output=json_output,
            exit_code=2,
        )

    slug = f"{domain}-{name}"
    full = f"woodard-energy/{slug}"
    echo(f"Creating {full} from template {TEMPLATE_REPO}...", json_output=json_output)

    try:
        run([
            "gh", "repo", "create", full,
            "--private",
            "--template", TEMPLATE_REPO,
            "--description", description or f"{display_name} module",
        ])
    except CommandError as e:
        emit_error(
            verb, f"gh repo create failed: {e.stderr}",
            json_output=json_output,
        )

    try:
        run(["gh", "repo", "clone", full])
    except CommandError as e:
        emit_error(
            verb,
            f"gh repo clone failed: {e.stderr}. "
            f"Note: {full} was created on GitHub — delete it manually to retry.",
            json_output=json_output,
        )

    repo = Path(slug)
    _patch_placeholders(
        repo, domain=domain, name=name, display_name=display_name
    )

    try:
        run(["git", "checkout", "-B", "dev"], cwd=repo)
        run(["git", "add", "-A"], cwd=repo)
        run(["git", "commit", "-m", "Initial scaffold"], cwd=repo)
        run(["git", "push", "-u", "origin", "dev"], cwd=repo)
    except CommandError as e:
        emit_error(verb, f"git failed: {e.stderr}", json_output=json_output)

    echo("", json_output=json_output)
    echo(f"✓ Created {full}", json_output=json_output)
    echo(f"  Local path: {repo.resolve()}", json_output=json_output)
    echo("", json_output=json_output)
    echo("Next steps:", json_output=json_output)
    echo(f"  1. cd {slug}", json_output=json_output)
    echo(
        "  2. Open a PR to register this module in the shell manifest",
        json_output=json_output,
    )
    echo("  3. Run `woodard-cli push-dev` after your first real commit", json_output=json_output)

    emit_success(
        verb,
        json_output=json_output,
        slug=slug,
        repo=full,
        local_path=str(repo.resolve()),
        domain=domain,
        name=name,
    )


def _patch_placeholders(
    repo: Path, *, domain: str, name: str, display_name: str
) -> None:
    slug = f"{domain}-{name}"

    mod_yaml = repo / "module.yaml"
    if mod_yaml.exists():
        text = mod_yaml.read_text(encoding="utf-8")
        text = text.replace(
            "display_name: REPLACE_ME", f"display_name: {display_name}"
        )
        text = text.replace("name: REPLACE_ME", f"name: {name}")
        text = text.replace("domain: REPLACE_ME", f"domain: {domain}")
        mod_yaml.write_text(text, encoding="utf-8")

    pyproj = repo / "pyproject.toml"
    if pyproj.exists():
        text = pyproj.read_text(encoding="utf-8")
        text = text.replace('name = "REPLACE_ME"', f'name = "{slug}"')
        pyproj.write_text(text, encoding="utf-8")

    claude = repo / ".claude" / "CLAUDE.md"
    if claude.exists():
        text = claude.read_text(encoding="utf-8")
        text = text.replace(
            "# Module: REPLACE_ME", f"# Module: {display_name}"
        )
        claude.write_text(text, encoding="utf-8")
