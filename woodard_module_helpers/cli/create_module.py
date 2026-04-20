import re
from pathlib import Path

import typer

from woodard_module_helpers.cli import app
from woodard_module_helpers.cli._shell import CommandError, run

VALID_DOMAINS = ("drilling", "geology", "land", "midstream", "reserves")
TEMPLATE_REPO = "woodard-energy/module-template"
KEBAB_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")


@app.command("create-module")
def create_module(
    domain: str = typer.Option(..., "--domain", "-d"),
    name: str = typer.Option(..., "--name", "-n"),
    display_name: str = typer.Option(..., "--display-name"),
    description: str = typer.Option("", "--description"),
) -> None:
    """Scaffold a new platform module from the template.

    Creates woodard-energy/<domain>-<name>, clones locally, patches placeholder
    fields, commits, and pushes to the dev branch.
    """
    if domain not in VALID_DOMAINS:
        typer.echo(
            f"domain must be one of {VALID_DOMAINS}, got {domain!r}", err=True
        )
        raise typer.Exit(code=2)
    if not KEBAB_RE.match(name):
        typer.echo(
            f"name must be kebab-case (lowercase, hyphens), got {name!r}",
            err=True,
        )
        raise typer.Exit(code=2)

    slug = f"{domain}-{name}"
    full = f"woodard-energy/{slug}"

    typer.echo(f"Creating {full} from template {TEMPLATE_REPO}...")
    try:
        run([
            "gh", "repo", "create", full,
            "--private",
            "--template", TEMPLATE_REPO,
            "--description", description or f"{display_name} module",
        ])
    except CommandError as e:
        typer.echo(f"gh repo create failed: {e.stderr}", err=True)
        raise typer.Exit(code=1) from e

    try:
        run(["gh", "repo", "clone", full])
    except CommandError as e:
        typer.echo(
            f"gh repo clone failed: {e.stderr}\n"
            f"Note: {full} was created on GitHub — delete it manually if "
            "you intend to retry with the same name.",
            err=True,
        )
        raise typer.Exit(code=1) from e

    repo = Path(slug)
    _patch_placeholders(repo, domain=domain, name=name, display_name=display_name)

    try:
        run(["git", "checkout", "-B", "dev"], cwd=repo)
        run(["git", "add", "-A"], cwd=repo)
        run(["git", "commit", "-m", "Initial scaffold"], cwd=repo)
        run(["git", "push", "-u", "origin", "dev"], cwd=repo)
    except CommandError as e:
        typer.echo(f"git failed: {e.stderr}", err=True)
        raise typer.Exit(code=1) from e

    typer.echo("")
    typer.echo(f"✓ Created {full}")
    typer.echo(f"  Local path: {repo.resolve()}")
    typer.echo("")
    typer.echo("Next steps:")
    typer.echo(f"  1. cd {slug}")
    typer.echo("  2. Open a PR to register this module in the shell manifest")
    typer.echo("     (modules.yaml in intelligence-platform repo)")
    typer.echo("  3. Run `woodard-cli push-dev` after adding your first real code")


def _patch_placeholders(
    repo: Path, *, domain: str, name: str, display_name: str
) -> None:
    slug = f"{domain}-{name}"

    mod_yaml = repo / "module.yaml"
    if mod_yaml.exists():
        text = mod_yaml.read_text(encoding="utf-8")
        # Replace display_name first so "name: REPLACE_ME" doesn't collide
        # with the substring "name: REPLACE_ME" inside "display_name: REPLACE_ME".
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
        text = text.replace("# Module: REPLACE_ME", f"# Module: {display_name}")
        claude.write_text(text, encoding="utf-8")
