import shutil
from pathlib import Path

import typer

from woodard_module_helpers.cli import app
from woodard_module_helpers.cli._shell import CommandError, run
from woodard_module_helpers.cli.create_module import (
    KEBAB_RE,
    TEMPLATE_REPO,
    VALID_DOMAINS,
    _patch_placeholders,
)

# Dirs/files in the source we do NOT copy into the platform repo.
EXCLUDE = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", "dist"}

# Files that must exist in the source for it to be convertible.
REQUIRED = ("app",)


@app.command("convert-to-platform")
def convert_to_platform(
    source: str = typer.Option(..., "--source", "-s"),
    domain: str = typer.Option(..., "--domain", "-d"),
    name: str = typer.Option(..., "--name", "-n"),
    display_name: str = typer.Option(..., "--display-name"),
    description: str = typer.Option("", "--description"),
) -> None:
    """Promote an existing personal-use project into a platform module.

    Creates a new woodard-energy/<slug> repo from the template, copies the
    source project's app/ (and similar) files into it, patches placeholders,
    and pushes to the dev branch. The source repo is untouched.

    Source project must have an `app/` directory (FastAPI convention). For
    v0.1 this is an opinionated conversion — projects that don't match the
    convention are rejected rather than heuristically reshaped.
    """
    if domain not in VALID_DOMAINS:
        typer.echo(f"domain must be one of {VALID_DOMAINS}", err=True)
        raise typer.Exit(code=2)
    if not KEBAB_RE.match(name):
        typer.echo("name must be kebab-case", err=True)
        raise typer.Exit(code=2)

    src = Path(source).resolve()
    missing = [r for r in REQUIRED if not (src / r).exists()]
    if missing:
        typer.echo(
            f"source missing required dirs: {missing} "
            f"(expected at least 'app/'); refusing to convert",
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
            "--description",
            description or f"{display_name} (converted from {src.name})",
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

    dest = Path(slug)
    _copy_source_into_dest(src, dest)
    _patch_placeholders(
        dest, domain=domain, name=name, display_name=display_name
    )

    try:
        run(["git", "checkout", "-B", "dev"], cwd=dest)
        run(["git", "add", "-A"], cwd=dest)
        run(
            ["git", "commit", "-m", f"Convert {src.name} to platform module"],
            cwd=dest,
        )
        run(["git", "push", "-u", "origin", "dev"], cwd=dest)
    except CommandError as e:
        typer.echo(f"git failed: {e.stderr}", err=True)
        raise typer.Exit(code=1) from e

    typer.echo("")
    typer.echo(f"\u2713 Converted {src} \u2192 {full}")
    typer.echo(f"  Local path: {dest.resolve()}")
    typer.echo("")
    typer.echo("Next steps:")
    typer.echo(
        "  1. Review the copied app/ code for platform-specific adjustments"
    )
    typer.echo("     (FORWARDED_PREFIX handling, identity, schema)")
    typer.echo("  2. Register the module in the shell manifest")
    typer.echo("  3. Run `woodard-cli push-dev`")


def _copy_source_into_dest(src: Path, dest: Path) -> None:
    """Copy source project files into dest, skipping EXCLUDE dirs and any file
    that already exists in dest (template scaffold wins for shared names).
    """
    for item in src.iterdir():
        if item.name in EXCLUDE:
            continue
        target = dest / item.name
        if target.exists() and target.is_file():
            # Template scaffolded this file — leave it alone.
            continue
        if item.is_dir():
            shutil.copytree(
                item,
                target,
                ignore=shutil.ignore_patterns(*EXCLUDE),
                dirs_exist_ok=True,
            )
        else:
            shutil.copy2(item, target)
